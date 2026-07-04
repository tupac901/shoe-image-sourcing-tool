from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from urllib.parse import quote_plus

import anyio
import httpx
from PIL import Image

from .adapters.search_pages import SearchPageAdapter
from .adapters.yandex_reverse_image import YandexReverseImageAdapter
from .config import FAST_PLATFORM_TIMEOUT_SECONDS, IMAGE_DOWNLOAD_TIMEOUT_SECONDS, MAX_IMAGES_PER_RUN
from .dedupe import group_duplicates
from .image_processing import compute_phash, make_thumbnail, process_to_3x4
from .models import ImageCandidate, RunManifest
from .relevance import find_reference_image, visual_similarity_score
from .storage import save_manifest
from .visual_analysis import analyze_image, profile_similarity_score

REJECTED_STATUS_LABELS = {"visual_mismatch", "download_failed"}
BROWSER_ASSET_MARKERS = ("r.bing.com/rp/", "www.bing.com/rp/", "bing.com/rp/")
SEARCH_PAGE_MARKERS = ("/images/search", "/search?", "/search/", "catalogsearch", "wholesale?searchtext", "/s?k=")
NON_PRODUCT_TITLE_MARKERS = (
    "youtube",
    "gameplay",
    "game play",
    "walkthrough",
    "trailer",
    "ace combat",
    "playstation",
    "ps1",
    "ps2",
    "xbox",
    "nintendo",
    "meme",
    "chart",
    "wallpaper",
    "clipart",
    "tutorial",
    "review video",
)
FALLBACK_PLATFORM = "bing_downloader"
FALLBACK_MIN_PROCESSED = 8
FALLBACK_LIMIT_PER_QUERY = 12
FALLBACK_MAX_QUERIES = 3
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


GENERIC_MODEL_TOKENS = {
    "men",
    "mens",
    "man",
    "women",
    "womens",
    "shoe",
    "shoes",
    "sneaker",
    "sneakers",
    "trainer",
    "trainers",
    "training",
    "white",
    "black",
    "blue",
    "navy",
    "grey",
    "gray",
    "red",
}


def _model_tokens(model: str | None) -> list[str]:
    if not model:
        return []
    return [
        token.lower()
        for token in model.replace("-", " ").replace("'", " ").split()
        if len(token) >= 3 and token.lower() not in GENERIC_MODEL_TOKENS
    ]


def text_relevance_score(candidate: ImageCandidate, manifest: RunManifest) -> int:
    facts = manifest.facts
    title = candidate.title or ""
    source_page_url = candidate.source_page_url or ""
    generic_title = title.lower().startswith(f"{candidate.platform} image for ")
    search_page_source = is_search_page_source(candidate)
    trusted_parts = [candidate.image_url or ""]
    if not generic_title:
        trusted_parts.append(title)
    if not search_page_source:
        trusted_parts.append(source_page_url)
    text = " ".join(item for item in trusted_parts if item).lower()
    score = 0
    if facts.sku and facts.sku.lower() in text:
        score += 8
    tokens = _model_tokens(facts.model)
    matched_tokens = sum(1 for token in tokens if token in text)
    if tokens and matched_tokens == len(tokens):
        score += 6
    elif matched_tokens:
        if facts.sku:
            score += min(matched_tokens * 2, 4)
        else:
            score += 4 if matched_tokens >= 2 else 1
    if facts.brand and facts.brand.lower() in text:
        score += 2
    return score


def is_textually_relevant(candidate: ImageCandidate, manifest: RunManifest) -> bool:
    return text_relevance_score(candidate, manifest) >= 4


def is_browser_asset(candidate: ImageCandidate) -> bool:
    url = (candidate.image_url or "").lower()
    return any(marker in url for marker in BROWSER_ASSET_MARKERS)


def is_search_page_source(candidate: ImageCandidate) -> bool:
    source_page_url = (candidate.source_page_url or "").lower()
    return any(marker in source_page_url for marker in SEARCH_PAGE_MARKERS)


def is_generic_search_candidate(candidate: ImageCandidate) -> bool:
    title = (candidate.title or "").lower()
    generic_title = title.startswith(f"{candidate.platform} image for ") or title.startswith("search results for ")
    return generic_title or is_search_page_source(candidate)


def has_non_product_title(candidate: ImageCandidate) -> bool:
    title = (candidate.title or "").lower()
    source = (candidate.source_page_url or "").lower()
    text = f"{title} {source}"
    return any(marker in text for marker in NON_PRODUCT_TITLE_MARKERS)


def has_specific_candidate_text(candidate: ImageCandidate) -> bool:
    title = (candidate.title or "").strip().lower()
    if not title:
        return False
    if title in {"untitled", "untitled image", "image", "photo", "product image"}:
        return False
    return not title.startswith(f"{candidate.platform} image for ") and not title.startswith("search results for ")


def has_rejected_status(candidate: ImageCandidate) -> bool:
    return any(label in REJECTED_STATUS_LABELS for label in candidate.status_labels)


def should_accept_candidate_match(candidate: ImageCandidate, text_score: int, visual_score: int, profile_score: int) -> bool:
    generic_search_candidate = is_generic_search_candidate(candidate)
    strong_text_match = text_score >= 10 and (visual_score >= 20 or profile_score >= 45)
    balanced_match = text_score >= 4 and visual_score >= 35 and profile_score >= 40
    image_first_match = text_score >= 4 and visual_score >= 65 and profile_score >= 50
    visual_only_match = not has_specific_candidate_text(candidate) and visual_score >= 78 and profile_score >= 72
    visual_profile_match = visual_score >= 55 and profile_score >= 88
    generic_search_match = generic_search_candidate and (
        (text_score >= 4 and visual_score >= 82 and profile_score >= 55) or visual_profile_match
    )
    non_generic_match = not generic_search_candidate and (
        strong_text_match or balanced_match or image_first_match or visual_profile_match
    )
    return generic_search_match or non_generic_match or visual_only_match


def prune_rejected_candidates(manifest: RunManifest) -> int:
    before = len(manifest.candidates)
    manifest.candidates = [candidate for candidate in manifest.candidates if not has_rejected_status(candidate)]
    return before - len(manifest.candidates)


def processed_count(manifest: RunManifest) -> int:
    return sum(1 for candidate in manifest.candidates if candidate.local_processed_path)


def fallback_queries(manifest: RunManifest) -> list[str]:
    facts = manifest.facts
    exact_parts = [facts.sku, facts.brand, facts.model]
    model_parts = [facts.brand, facts.model]
    queries = [
        " ".join(part.strip() for part in exact_parts if part and part.strip()),
        " ".join(part.strip() for part in model_parts if part and part.strip()),
        f"{facts.sku} shoe" if facts.sku else None,
    ]
    unique: list[str] = []
    seen: set[str] = set()
    for query in queries:
        if not query:
            continue
        normalized = " ".join(query.split())
        if len(normalized) < 4 or normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        unique.append(normalized)
    return unique[:FALLBACK_MAX_QUERIES]


def download_bing_images(query: str, output_dir: Path, limit: int = FALLBACK_LIMIT_PER_QUERY) -> Path:
    from better_bing_image_downloader import downloader

    downloader(
        query,
        limit=limit,
        output_dir=str(output_dir),
        force_replace=True,
        timeout=35,
        verbose=False,
        name="fallback",
        max_workers=4,
        min_dimension=320,
    )
    return output_dir / query


def _manifest_sources(download_dir: Path) -> dict[str, str]:
    manifest_path = download_dir / "_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {name: html.unescape(url) for name, url in raw.items() if isinstance(name, str) and isinstance(url, str)}


def candidates_from_downloaded_images(download_dir: Path, query: str) -> list[ImageCandidate]:
    sources = _manifest_sources(download_dir)
    candidates: list[ImageCandidate] = []
    if not download_dir.exists():
        return candidates
    for image_path in sorted(download_dir.iterdir()):
        if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        source_url = sources.get(image_path.name, "")
        digest = hashlib.sha1(f"{query}:{image_path.name}:{source_url}".encode("utf-8")).hexdigest()[:16]
        candidates.append(
            ImageCandidate(
                id=digest,
                platform=FALLBACK_PLATFORM,
                source_page_url=source_url or f"https://www.bing.com/images/search?q={quote_plus(query)}",
                image_url=source_url,
                title=query,
                local_original_path=image_path.as_posix(),
                status_labels=["downloaded_image_fallback"],
            )
        )
    return candidates


async def run_image_downloader_fallback(
    manifest: RunManifest,
    run_dir: Path,
    hashes: dict[str, str],
    reference_path: Path | None,
) -> None:
    if processed_count(manifest) >= FALLBACK_MIN_PROCESSED:
        return
    queries = fallback_queries(manifest)
    if not queries:
        manifest.logs.append("image fallback skipped: no exact sku/model query")
        return
    manifest.logs.append(f"image fallback started, current usable images {processed_count(manifest)}")
    fallback_root = run_dir / "originals" / FALLBACK_PLATFORM
    for query in queries:
        if processed_count(manifest) >= FALLBACK_MIN_PROCESSED:
            break
        try:
            download_dir = await anyio.to_thread.run_sync(download_bing_images, query, fallback_root, FALLBACK_LIMIT_PER_QUERY)
            candidates = candidates_from_downloaded_images(download_dir, query)
            if not candidates:
                manifest.logs.append(f"{FALLBACK_PLATFORM}: no downloaded images for {query}")
                continue
            manifest.candidates.extend(candidates)
            manifest.logs.append(f"{FALLBACK_PLATFORM}: downloaded {len(candidates)} images for {query}")
            rejected = await download_and_process_candidates(manifest, run_dir, candidates, hashes, reference_path)
            removed = prune_rejected_candidates(manifest)
            if rejected or removed:
                manifest.logs.append(f"{FALLBACK_PLATFORM}: removed {removed or rejected} unusable or unrelated images")
            save_manifest(manifest, run_dir)
        except Exception as exc:
            manifest.logs.append(f"{FALLBACK_PLATFORM}: failed for {query}: {exc}")


async def collect_candidates(manifest: RunManifest, run_dir: Path, limit_per_platform: int = 6) -> RunManifest:
    manifest.status = "running"
    manifest.logs.append("crawl started in fast background mode")
    save_manifest(manifest, run_dir)
    hashes: dict[str, str] = {}
    reference_path = find_reference_image(run_dir)
    if reference_path:
        manifest.visual_profile = analyze_image(reference_path)
        manifest.logs.append("reference image analyzed for visual-first matching")
        save_manifest(manifest, run_dir)
    await run_image_downloader_fallback(manifest, run_dir, hashes, reference_path)
    save_manifest(manifest, run_dir)

    max_queries_per_platform = min(8, len(manifest.queries))

    for platform in manifest.platforms:
        if processed_count(manifest) >= MAX_IMAGES_PER_RUN:
            manifest.logs.append("global image limit reached before slow platform crawling")
            break
        target_processed_per_platform = 12 if platform == "bing_images" else min(4, limit_per_platform)
        platform_total = 0
        platform_processed = 0
        platform_queries = manifest.queries[:1] if platform == "yandex_reverse_image" else manifest.queries[:max_queries_per_platform]
        for query in platform_queries:
            try:
                adapter = (
                    YandexReverseImageAdapter(reference_path)
                    if platform == "yandex_reverse_image"
                    else SearchPageAdapter(platform)
                )
                search_limit = 18 if platform == "bing_images" else limit_per_platform
                candidates = await adapter.search(query, limit=search_limit, timeout=FAST_PLATFORM_TIMEOUT_SECONDS)
                if platform == "bing_images":
                    candidates = sorted(candidates, key=lambda candidate: text_relevance_score(candidate, manifest), reverse=True)
                if not any(candidate.image_url or candidate.local_original_path for candidate in candidates):
                    manifest.logs.append(f"{platform}: search-page only for {query}, skipped gallery placeholders")
                    platform_total += len(candidates)
                    continue
                for candidate in candidates:
                    if platform == "ozon" and "competitor_reference_only" not in candidate.status_labels:
                        candidate.status_labels.append("competitor_reference_only")
                manifest.candidates.extend(candidates)
                platform_total += len(candidates)
                manifest.logs.append(f"{platform}: collected {len(candidates)} entries for {query}")
                rejected = await download_and_process_candidates(manifest, run_dir, candidates, hashes, reference_path)
                removed = prune_rejected_candidates(manifest)
                if rejected or removed:
                    manifest.logs.append(f"{platform}: removed {removed or rejected} unusable or unrelated images")
                    save_manifest(manifest, run_dir)
                platform_processed = sum(
                    1
                    for candidate in manifest.candidates
                    if candidate.platform == platform and candidate.local_processed_path
                )
                if processed_count(manifest) >= MAX_IMAGES_PER_RUN:
                    manifest.logs.append("global image limit reached")
                    break
                if platform_processed >= target_processed_per_platform:
                    manifest.logs.append(f"{platform}: enough usable images, stop after {platform_processed} processed")
                    break
            except Exception as exc:
                manifest.logs.append(f"{platform}: failed for {query}: {exc}")
        manifest.logs.append(f"{platform}: search step done, {platform_total} entries")
        save_manifest(manifest, run_dir)
    group_duplicates(manifest.candidates, hashes)
    manifest.status = "complete"
    manifest.logs.append("run complete")
    save_manifest(manifest, run_dir)
    return manifest


async def download_and_process_candidates(
    manifest: RunManifest,
    run_dir: Path,
    candidates_to_process: list[ImageCandidate] | None = None,
    hashes: dict[str, str] | None = None,
    reference_path: Path | None = None,
) -> int:
    hashes = hashes if hashes is not None else {}
    rejected = 0
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=IMAGE_DOWNLOAD_TIMEOUT_SECONDS,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"},
    ) as client:
        source_candidates = candidates_to_process if candidates_to_process is not None else manifest.candidates
        candidates = [candidate for candidate in source_candidates if candidate.image_url or candidate.local_original_path]
        semaphore = anyio.Semaphore(4)

        async def process_one(candidate):
            nonlocal rejected
            async with semaphore:
                if not await download_and_process_one(client, candidate, run_dir, hashes, manifest, reference_path):
                    rejected += 1

        async with anyio.create_task_group() as task_group:
            for candidate in candidates:
                task_group.start_soon(process_one, candidate)
    if candidates_to_process is None:
        group_duplicates(manifest.candidates, hashes)
    return rejected


async def download_and_process_one(
    client: httpx.AsyncClient,
    candidate,
    run_dir: Path,
    hashes: dict[str, str],
    manifest: RunManifest,
    reference_path: Path | None = None,
) -> bool:
    if not candidate.image_url and not candidate.local_original_path:
        return True
    try:
        if is_browser_asset(candidate):
            candidate.status_labels.append("visual_mismatch")
            manifest.logs.append(f"{candidate.platform}: rejected browser/search-ui asset {candidate.image_url}")
            return False
        original_path = Path(candidate.local_original_path) if candidate.local_original_path else await download_image(client, candidate.image_url, run_dir / "originals", candidate.id)
        with Image.open(original_path) as image:
            candidate.width, candidate.height = image.size
        if min(candidate.width or 0, candidate.height or 0) < 240:
            candidate.status_labels.append("visual_mismatch")
            manifest.logs.append(f"{candidate.platform}: rejected too-small image {original_path.name}")
            return False
        text_score = text_relevance_score(candidate, manifest)
        visual_score = visual_similarity_score(reference_path, original_path)
        profile_score = profile_similarity_score(reference_path, original_path)
        candidate.status_labels.append(f"text_score_{text_score}")
        candidate.status_labels.append(f"visual_score_{visual_score}")
        candidate.status_labels.append(f"profile_score_{profile_score}")
        if has_non_product_title(candidate):
            candidate.status_labels.append("visual_mismatch")
            manifest.logs.append(f"{candidate.platform}: rejected non-product title {candidate.title}")
            return False
        if not should_accept_candidate_match(candidate, text_score, visual_score, profile_score):
            candidate.status_labels.append("visual_mismatch")
            manifest.logs.append(
                f"{candidate.platform}: rejected image {original_path.name} text_score={text_score} visual_score={visual_score} profile_score={profile_score}"
            )
            return False
        thumb_path = run_dir / "thumbnails" / f"{candidate.id}.jpg"
        processed_path = run_dir / "processed_3x4" / f"{candidate.id}.jpg"
        make_thumbnail(original_path, thumb_path)
        process_to_3x4(original_path, processed_path)
        candidate.local_original_path = original_path.as_posix()
        candidate.local_thumbnail_path = thumb_path.as_posix()
        candidate.local_processed_path = processed_path.as_posix()
        hashes[candidate.id] = compute_phash(original_path)
        return True
    except Exception as exc:
        candidate.status_labels.append("download_failed")
        manifest.logs.append(f"{candidate.platform}: image download failed {candidate.image_url}: {exc}")
        return False


async def download_image(client: httpx.AsyncClient, image_url: str, output_dir: Path, candidate_id: str) -> Path:
    response = await client.get(image_url)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    suffix = ".jpg"
    if "png" in content_type:
        suffix = ".png"
    elif "webp" in content_type:
        suffix = ".webp"
    elif image_url.lower().split("?")[0].endswith(".png"):
        suffix = ".png"
    elif image_url.lower().split("?")[0].endswith(".webp"):
        suffix = ".webp"
    path = output_dir / f"{candidate_id}{suffix}"
    path.write_bytes(response.content)
    return path
