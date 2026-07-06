from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path
from urllib.parse import quote_plus, unquote

import anyio
import httpx
from PIL import Image

from .adapters.poizon_visual import PoizonVisualAdapter
from .adapters.search_pages import SearchPageAdapter
from .adapters.yandex_reverse_image import YandexReverseImageAdapter
from .config import FAST_PLATFORM_TIMEOUT_SECONDS, IMAGE_DOWNLOAD_TIMEOUT_SECONDS, MAX_IMAGES_PER_RUN
from .dedupe import group_duplicates
from .feature_similarity import orb_similarity_score
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
IMAGE_FIRST_MIN_PROCESSED = 3
FALLBACK_LIMIT_PER_QUERY = 12
FALLBACK_MAX_QUERIES = 3
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
POIZON_VISUAL_HINT_TIMEOUT_SECONDS = 25
VISUAL_HINT_STOP_TOKENS = {
    "ipad",
    "upload",
    "uploads",
    "product",
    "products",
    "image",
    "images",
    "media",
    "origin",
    "thumb",
    "thumbnail",
    "cache",
    "static",
    "jpg",
    "jpeg",
    "png",
    "webp",
    "avif",
}
VISUAL_HINT_BRAND_TOKENS = {
    "adidas",
    "asics",
    "balenciaga",
    "converse",
    "fila",
    "hoka",
    "jordan",
    "mizuno",
    "newbalance",
    "nike",
    "onitsuka",
    "puma",
    "reebok",
    "saucony",
    "salomon",
    "skechers",
    "vans",
}
VISUAL_HINT_BRAND_DISPLAY = {
    "newbalance": "New Balance",
}


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
    "cream",
    "pink",
    "silver",
    "soul",
    "sole",
    "low",
    "top",
    "lowtop",
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


def is_visual_fallback_candidate(candidate: ImageCandidate) -> bool:
    return "visual_fallback_without_sku" in candidate.status_labels


def is_poizon_sku_search_result(candidate: ImageCandidate) -> bool:
    return "poizon_sku_search_result" in candidate.status_labels


def is_poizon_visual_hint_result(candidate: ImageCandidate) -> bool:
    return "poizon_visual_hint_result" in candidate.status_labels


def is_poizon_visual_numeric_hint_result(candidate: ImageCandidate) -> bool:
    return "poizon_visual_numeric_hint" in candidate.status_labels


def _compact(value: str | None) -> str:
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def candidate_search_text(candidate: ImageCandidate) -> str:
    return " ".join(
        item
        for item in [candidate.title or "", candidate.source_page_url or "", candidate.image_url or ""]
        if item
    ).lower()


def has_exact_sku_match(candidate: ImageCandidate, manifest: RunManifest) -> bool:
    sku = _compact(manifest.facts.sku)
    if not sku:
        return True
    return sku in _compact(candidate_search_text(candidate))


def should_accept_candidate_for_manifest(
    candidate: ImageCandidate,
    manifest: RunManifest,
    text_score: int,
    visual_score: int,
    profile_score: int,
    feature_score: int = 50,
) -> bool:
    if candidate.platform == "poizon_visual":
        image_only_result = is_poizon_visual_hint_result(candidate)
        has_manifest_sku = bool(_compact(manifest.facts.sku)) and not image_only_result
        exact_sku_match = has_manifest_sku and has_exact_sku_match(candidate, manifest)
        if has_manifest_sku and not exact_sku_match and not is_visual_fallback_candidate(candidate):
            return False
        if image_only_result:
            if is_poizon_visual_numeric_hint_result(candidate) and visual_score >= 90 and profile_score >= 75 and feature_score >= 2:
                return True
            return feature_score >= 18 and visual_score >= 70 and profile_score >= 45
        if is_visual_fallback_candidate(candidate):
            if is_poizon_sku_search_result(candidate):
                return (visual_score >= 78 and profile_score >= 50) or (visual_score >= 90 and profile_score >= 45)
            return feature_score >= 35 and visual_score >= 88 and profile_score >= 72
        if exact_sku_match:
            return (
                feature_score >= 25
                and ((visual_score >= 82 and profile_score >= 72) or (visual_score >= 70 and profile_score >= 84))
            ) or (visual_score >= 78 and profile_score >= 50) or (visual_score >= 90 and profile_score >= 45)
        return feature_score >= 18 and visual_score >= 70 and profile_score >= 45
    return should_accept_candidate_match(candidate, text_score, visual_score, profile_score)


def filter_candidates_for_manifest(
    candidates: list[ImageCandidate],
    manifest: RunManifest,
    visual_fallback_limit: int = 0,
) -> tuple[list[ImageCandidate], int]:
    if not manifest.facts.sku:
        return candidates, 0
    poizon_candidates = [candidate for candidate in candidates if candidate.platform == "poizon_visual"]
    if not poizon_candidates:
        return candidates, 0
    if any(is_poizon_visual_hint_result(candidate) for candidate in poizon_candidates):
        return candidates, 0
    exact_poizon = [candidate for candidate in poizon_candidates if has_exact_sku_match(candidate, manifest)]
    if exact_poizon:
        kept: list[ImageCandidate] = []
        removed = 0
        for candidate in candidates:
            if candidate.platform == "poizon_visual" and not has_exact_sku_match(candidate, manifest):
                candidate.status_labels.append("visual_mismatch")
                candidate.status_labels.append("sku_mismatch")
                removed += 1
                continue
            kept.append(candidate)
        return kept, removed
    fallback_remaining = visual_fallback_limit
    kept = []
    removed = 0
    for candidate in candidates:
        if candidate.platform != "poizon_visual":
            kept.append(candidate)
            continue
        if fallback_remaining > 0:
            candidate.status_labels.append("visual_fallback_without_sku")
            kept.append(candidate)
            fallback_remaining -= 1
        else:
            candidate.status_labels.append("visual_mismatch")
            candidate.status_labels.append("sku_mismatch")
            removed += 1
    return kept, removed


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


def image_first_processed_count(manifest: RunManifest) -> int:
    return sum(
        1
        for candidate in manifest.candidates
        if candidate.local_processed_path and candidate.platform in {"yandex_reverse_image", "poizon_visual"}
    )


def ensure_image_first_platforms(manifest: RunManifest, has_reference_image: bool) -> None:
    if not has_reference_image or "yandex_reverse_image" not in manifest.platforms:
        return
    manifest.platforms = [platform for platform in manifest.platforms if platform != "yandex_reverse_image"]
    manifest.platforms.insert(0, "yandex_reverse_image")


def should_skip_fallback(manifest: RunManifest) -> bool:
    return image_first_processed_count(manifest) >= IMAGE_FIRST_MIN_PROCESSED


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


def _display_token(token: str) -> str:
    upper_tokens = {"asics", "gel", "gt", "ex", "cn", "fl", "tr", "ff", "jog"}
    if token.isdigit():
        return token
    if token.lower() in upper_tokens or any(ch.isdigit() for ch in token):
        return token.upper()
    return token.capitalize()


def poizon_visual_hint_queries(candidates: list[ImageCandidate], brand: str | None = None, limit: int = 3) -> list[str]:
    seed_brands = {_compact(brand)} if brand else set()
    hints: list[tuple[int, str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        for haystack in [candidate.title or "", candidate.image_url or "", candidate.source_page_url or ""]:
            decoded = unquote(haystack).lower()
            chunks = re.split(r"[^a-z0-9]+", decoded)
            for index, token in enumerate(chunks):
                compact_token = _compact(token)
                compact_pair = _compact("".join(chunks[index : index + 2]))
                if compact_token in VISUAL_HINT_BRAND_TOKENS or compact_token in seed_brands:
                    brand_token = compact_token
                    raw_start = index + 1
                elif compact_pair in VISUAL_HINT_BRAND_TOKENS or compact_pair in seed_brands:
                    brand_token = compact_pair
                    raw_start = index + 2
                else:
                    continue
                raw = []
                for next_token in chunks[raw_start : raw_start + 10]:
                    if not next_token or next_token in VISUAL_HINT_STOP_TOKENS:
                        continue
                    if len(next_token) > 18:
                        continue
                    raw.append(next_token)
                    if len(raw) >= 7:
                        break
                if len(raw) < 2:
                    continue
                display_brand = VISUAL_HINT_BRAND_DISPLAY.get(brand_token, _display_token(brand_token))
                hint = " ".join([display_brand, *[_display_token(item) for item in raw]])
                normalized = hint.lower()
                if normalized in seen:
                    continue
                seen.add(normalized)
                score = sum(12 for item in raw if any(ch.isdigit() for ch in item)) + min(len(raw), 8)
                hints.append((score, hint))
    hints.sort(key=lambda item: item[0], reverse=True)
    return [hint for _, hint in hints[:limit]]


def is_numeric_visual_hint(query: str) -> bool:
    return any(any(ch.isdigit() for ch in token) for token in query.split())


def numeric_visual_hint_tokens(query: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for token in query.split():
        compact = _compact(token)
        if not compact or not any(ch.isdigit() for ch in compact):
            continue
        has_letter = any(ch.isalpha() for ch in compact)
        digits = sum(1 for ch in compact if ch.isdigit())
        if not ((has_letter and len(compact) >= 5) or digits >= 4):
            continue
        if compact in seen:
            continue
        seen.add(compact)
        tokens.append(compact)
    return tokens


def candidate_matches_numeric_visual_hint(candidate: ImageCandidate, query: str) -> bool:
    tokens = numeric_visual_hint_tokens(query)
    if not tokens:
        return False
    text = _compact(candidate_search_text(candidate))
    return any(token in text for token in tokens)


def visual_hint_identity_signature(query: str) -> str:
    chunks = re.split(r"[^a-z0-9]+", query.lower())
    identity: list[str] = []
    for token in chunks:
        compact = _compact(token)
        if not compact:
            continue
        if compact in VISUAL_HINT_BRAND_TOKENS or compact in GENERIC_MODEL_TOKENS or compact in VISUAL_HINT_STOP_TOKENS:
            continue
        has_letter = any(ch.isalpha() for ch in compact)
        digits = sum(1 for ch in compact if ch.isdigit())
        if has_letter and digits and len(compact) >= 5 and identity:
            break
        identity.append(compact)
        if len(identity) >= 4:
            break
    return "".join(identity)


def candidate_matches_visual_hint_identity(candidate: ImageCandidate, query: str) -> bool:
    signature = visual_hint_identity_signature(query)
    if len(signature) < 4:
        return False
    return signature in _compact(candidate_search_text(candidate))


def poizon_visual_direct_reverse_candidates(candidates: list[ImageCandidate], limit: int = 6) -> list[ImageCandidate]:
    direct: list[ImageCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        image_url = candidate.image_url or ""
        source_page_url = candidate.source_page_url or ""
        if not image_url:
            continue
        lowered = image_url.lower()
        if not source_page_url.lower().startswith("https://poizon.ru/product/"):
            continue
        if image_url in seen:
            continue
        seen.add(image_url)
        direct.append(
            ImageCandidate(
                id=hashlib.sha1(f"poizon_visual:reverse:{image_url}".encode("utf-8")).hexdigest()[:16],
                platform="poizon_visual",
                source_page_url=source_page_url,
                image_url=image_url,
                title=candidate.title if candidate.title and not candidate.title.startswith("yandex_reverse_image image for ") else "Poizon visual reverse image match",
                status_labels=["poizon_visual_hint_result", "poizon_direct_reverse_image"],
            )
        )
        if len(direct) >= limit:
            break
    return direct


def poizon_visual_generic_reverse_candidates(candidates: list[ImageCandidate], limit: int = 6) -> list[ImageCandidate]:
    generic: list[ImageCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        image_url = candidate.image_url or ""
        if not image_url or image_url in seen:
            continue
        lowered_image_url = image_url.lower()
        if is_browser_asset(candidate) or any(marker in lowered_image_url for marker in SEARCH_PAGE_MARKERS):
            continue
        seen.add(image_url)
        generic.append(
            ImageCandidate(
                id=hashlib.sha1(f"poizon_visual:generic-reverse:{image_url}".encode("utf-8")).hexdigest()[:16],
                platform="poizon_visual",
                source_page_url=candidate.source_page_url or image_url,
                image_url=image_url,
                title=candidate.title if candidate.title and not candidate.title.startswith("yandex_reverse_image image for ") else "Visual reverse image match",
                status_labels=["poizon_visual_hint_result", "poizon_generic_reverse_image"],
            )
        )
        if len(generic) >= limit:
            break
    return generic


def platform_queries_for_manifest(platform: str, manifest: RunManifest, max_queries_per_platform: int) -> list[str]:
    if platform == "poizon_visual":
        return []
    if platform == "yandex_reverse_image":
        if manifest.queries:
            return manifest.queries[:1]
        fallback = " ".join(
            part.strip()
            for part in [manifest.facts.sku, manifest.facts.brand, manifest.facts.model]
            if part and part.strip()
        )
        return [fallback or "reference image"]
    return manifest.queries[:max_queries_per_platform]


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
                title=f"{FALLBACK_PLATFORM} image for {query}",
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
    if should_skip_fallback(manifest):
        manifest.logs.append(f"image fallback skipped: image-first matches reached {image_first_processed_count(manifest)}")
        return
    if manifest.platforms == ["poizon_visual"]:
        manifest.logs.append("image fallback skipped: poizon exact-match mode")
        return
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
    try:
        hashes: dict[str, str] = {}
        reference_path = find_reference_image(run_dir)
        ensure_image_first_platforms(manifest, bool(reference_path))
        if reference_path:
            manifest.visual_profile = analyze_image(reference_path)
            manifest.logs.append("reference image analyzed for visual-first matching")
            save_manifest(manifest, run_dir)

        max_queries_per_platform = min(8, len(manifest.queries))
        poizon_visual_hints: list[str] = []
        poizon_image_search: list[ImageCandidate] = []
        poizon_direct_reverse: list[ImageCandidate] = []
        poizon_generic_reverse: list[ImageCandidate] = []
        if reference_path and "poizon_visual" in manifest.platforms:
            poizon_image_search = await PoizonVisualAdapter().search_by_image(
                reference_path,
                limit=limit_per_platform,
                timeout=POIZON_VISUAL_HINT_TIMEOUT_SECONDS,
            )
            if any(candidate.image_url for candidate in poizon_image_search):
                manifest.logs.append(f"poizon_visual: collected {len(poizon_image_search)} entries from Poizon image search")
                save_manifest(manifest, run_dir)
            else:
                poizon_image_search = []
                manifest.logs.append("poizon_visual: Poizon image search returned no product images")
                hint_candidates = await YandexReverseImageAdapter(reference_path).search(
                    "reference image",
                    limit=20,
                    timeout=POIZON_VISUAL_HINT_TIMEOUT_SECONDS,
                )
                poizon_visual_hints = poizon_visual_hint_queries(hint_candidates, limit=6)
                poizon_direct_reverse = poizon_visual_direct_reverse_candidates(hint_candidates)
                if not poizon_visual_hints and not poizon_direct_reverse:
                    poizon_generic_reverse = poizon_visual_generic_reverse_candidates(hint_candidates)
                    if poizon_generic_reverse:
                        manifest.logs.append(
                            f"poizon_visual: ignored {len(poizon_generic_reverse)} non-Poizon reverse image candidates; final results require poizon.ru/product links"
                        )
                if poizon_visual_hints:
                    manifest.logs.append(f"poizon_visual: visual hint queries {poizon_visual_hints}")
                    save_manifest(manifest, run_dir)

        for platform in manifest.platforms:
            if processed_count(manifest) >= MAX_IMAGES_PER_RUN:
                manifest.logs.append("global image limit reached before slow platform crawling")
                break
            target_processed_per_platform = 12 if platform == "bing_images" else min(4, limit_per_platform)
            platform_total = 0
            platform_processed = 0
            platform_queries = platform_queries_for_manifest(platform, manifest, max_queries_per_platform)
            if platform == "poizon_visual" and poizon_visual_hints:
                platform_queries = [*poizon_visual_hints, *platform_queries]
            if platform == "poizon_visual" and poizon_image_search:
                manifest.candidates.extend(poizon_image_search)
                platform_total += len(poizon_image_search)
                rejected = await download_and_process_candidates(manifest, run_dir, poizon_image_search, hashes, reference_path)
                removed = prune_rejected_candidates(manifest)
                if rejected or removed:
                    manifest.logs.append(f"poizon_visual: removed {removed or rejected} unusable or unrelated Poizon image-search images")
                    save_manifest(manifest, run_dir)
                platform_processed = sum(
                    1
                    for candidate in manifest.candidates
                    if candidate.platform == platform and candidate.local_processed_path
                )
                if platform_processed >= target_processed_per_platform:
                    manifest.logs.append(f"{platform}: target image count reached ({platform_processed})")
                    save_manifest(manifest, run_dir)
                    continue
                if not platform_queries and not poizon_direct_reverse:
                    manifest.logs.append(f"{platform}: search step done, {platform_total} entries")
                    save_manifest(manifest, run_dir)
                    continue
            if platform == "poizon_visual" and poizon_direct_reverse:
                manifest.candidates.extend(poizon_direct_reverse)
                platform_total += len(poizon_direct_reverse)
                manifest.logs.append(f"poizon_visual: collected {len(poizon_direct_reverse)} direct reverse Poizon images")
                rejected = await download_and_process_candidates(manifest, run_dir, poizon_direct_reverse, hashes, reference_path)
                removed = prune_rejected_candidates(manifest)
                if rejected or removed:
                    manifest.logs.append(f"poizon_visual: removed {removed or rejected} unusable or unrelated direct reverse images")
                    save_manifest(manifest, run_dir)
            if platform == "poizon_visual" and not platform_queries and not poizon_direct_reverse and not poizon_generic_reverse:
                manifest.logs.append("poizon_visual: no Poizon product found from uploaded image, skipped text/model/sku fallback")
                manifest.logs.append(f"{platform}: search step done, 0 entries")
                save_manifest(manifest, run_dir)
                continue
            if platform == "poizon_visual" and not platform_queries and not poizon_direct_reverse and poizon_generic_reverse:
                manifest.logs.append("poizon_visual: no Poizon product query/link derived from uploaded image")
                manifest.logs.append(f"{platform}: search step done, 0 entries")
                save_manifest(manifest, run_dir)
                continue
            for query in platform_queries:
                try:
                    if platform == "yandex_reverse_image":
                        adapter = YandexReverseImageAdapter(reference_path)
                    elif platform == "poizon_visual":
                        adapter = PoizonVisualAdapter()
                    else:
                        adapter = SearchPageAdapter(platform)
                    search_limit = 18 if platform == "bing_images" else limit_per_platform
                    candidates = await adapter.search(query, limit=search_limit, timeout=FAST_PLATFORM_TIMEOUT_SECONDS)
                    if platform == "poizon_visual" and query in poizon_visual_hints:
                        for candidate in candidates:
                            if "poizon_visual_hint_result" not in candidate.status_labels:
                                candidate.status_labels.append("poizon_visual_hint_result")
                            if (
                                is_numeric_visual_hint(query)
                                and (
                                    candidate_matches_numeric_visual_hint(candidate, query)
                                    or candidate_matches_visual_hint_identity(candidate, query)
                                )
                                and "poizon_visual_numeric_hint" not in candidate.status_labels
                            ):
                                candidate.status_labels.append("poizon_visual_numeric_hint")
                    if platform == "bing_images":
                        candidates = sorted(candidates, key=lambda candidate: text_relevance_score(candidate, manifest), reverse=True)
                    visual_fallback_limit = 3 if platform == "poizon_visual" else 0
                    candidates, prefiltered = filter_candidates_for_manifest(candidates, manifest, visual_fallback_limit)
                    if prefiltered:
                        manifest.logs.append(f"{platform}: skipped {prefiltered} non-exact sku candidates before download")
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
        await run_image_downloader_fallback(manifest, run_dir, hashes, reference_path)
        group_duplicates(manifest.candidates, hashes)
        manifest.status = "complete"
        if processed_count(manifest) == 0:
            manifest.logs.append("no exact product image found")
        manifest.logs.append("run complete")
        save_manifest(manifest, run_dir)
    except Exception as exc:
        manifest.status = "failed"
        manifest.logs.append(f"run failed: {exc}")
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
        if (
            candidate.platform == "poizon_visual"
            and manifest.facts.sku
            and not has_exact_sku_match(candidate, manifest)
            and not is_visual_fallback_candidate(candidate)
            and not is_poizon_visual_hint_result(candidate)
        ):
            candidate.status_labels.append("visual_mismatch")
            candidate.status_labels.append("sku_mismatch")
            manifest.logs.append(
                f"{candidate.platform}: rejected non-exact sku image before download expected_sku={manifest.facts.sku} title={candidate.title}"
            )
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
        feature_score = orb_similarity_score(reference_path, original_path)
        candidate.status_labels.append(f"text_score_{text_score}")
        candidate.status_labels.append(f"visual_score_{visual_score}")
        candidate.status_labels.append(f"profile_score_{profile_score}")
        candidate.status_labels.append(f"feature_score_{feature_score}")
        if has_non_product_title(candidate):
            candidate.status_labels.append("visual_mismatch")
            manifest.logs.append(f"{candidate.platform}: rejected non-product title {candidate.title}")
            return False
        if not should_accept_candidate_for_manifest(candidate, manifest, text_score, visual_score, profile_score, feature_score):
            candidate.status_labels.append("visual_mismatch")
            manifest.logs.append(
                f"{candidate.platform}: rejected image {original_path.name} text_score={text_score} visual_score={visual_score} profile_score={profile_score} feature_score={feature_score}"
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
    elif "avif" in content_type:
        suffix = ".avif"
    elif image_url.lower().split("?")[0].endswith(".png"):
        suffix = ".png"
    elif image_url.lower().split("?")[0].endswith(".webp"):
        suffix = ".webp"
    elif image_url.lower().split("?")[0].endswith(".avif"):
        suffix = ".avif"
    path = output_dir / f"{candidate_id}{suffix}"
    path.write_bytes(response.content)
    return path
