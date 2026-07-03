from __future__ import annotations

from pathlib import Path

import anyio
import httpx
from PIL import Image

from .adapters.search_pages import SearchPageAdapter
from .config import FAST_PLATFORM_TIMEOUT_SECONDS, IMAGE_DOWNLOAD_TIMEOUT_SECONDS
from .dedupe import group_duplicates
from .image_processing import compute_phash, make_thumbnail, process_to_3x4
from .models import ImageCandidate, RunManifest
from .relevance import find_reference_image, is_visually_related
from .storage import save_manifest


def _model_tokens(model: str | None) -> list[str]:
    if not model:
        return []
    return [token.lower() for token in model.replace("-", " ").split() if len(token) >= 3]


def is_textually_relevant(candidate: ImageCandidate, manifest: RunManifest) -> bool:
    facts = manifest.facts
    text = " ".join(
        item for item in [candidate.title, candidate.source_page_url, candidate.image_url] if item
    ).lower()
    if facts.sku and facts.sku.lower() in text:
        return True
    tokens = _model_tokens(facts.model)
    if tokens and all(token in text for token in tokens[:3]):
        return True
    if facts.brand and facts.model and facts.brand.lower() in text and any(token in text for token in tokens):
        return True
    return False


async def collect_candidates(manifest: RunManifest, run_dir: Path, limit_per_platform: int = 6) -> RunManifest:
    manifest.status = "running"
    manifest.logs.append("crawl started in fast background mode")
    save_manifest(manifest, run_dir)
    hashes: dict[str, str] = {}
    reference_path = find_reference_image(run_dir)

    target_processed_per_platform = min(4, limit_per_platform)
    max_queries_per_platform = min(5, len(manifest.queries))

    for platform in manifest.platforms:
        platform_total = 0
        platform_processed = 0
        for query in manifest.queries[:max_queries_per_platform]:
            try:
                adapter = SearchPageAdapter(platform)
                candidates = await adapter.search(query, limit=limit_per_platform, timeout=FAST_PLATFORM_TIMEOUT_SECONDS)
                if platform == "bing_images":
                    before_text_filter = len(candidates)
                    candidates = [candidate for candidate in candidates if is_textually_relevant(candidate, manifest)]
                    removed = before_text_filter - len(candidates)
                    if removed:
                        manifest.logs.append(f"{platform}: removed {removed} textually unrelated results")
                for candidate in candidates:
                    if platform == "ozon" and "competitor_reference_only" not in candidate.status_labels:
                        candidate.status_labels.append("competitor_reference_only")
                manifest.candidates.extend(candidates)
                platform_total += len(candidates)
                manifest.logs.append(f"{platform}: collected {len(candidates)} entries for {query}")
                rejected = await download_and_process_candidates(manifest, run_dir, candidates, hashes, reference_path)
                if rejected:
                    manifest.candidates = [
                        candidate for candidate in manifest.candidates if "visual_mismatch" not in candidate.status_labels
                    ]
                    manifest.logs.append(f"{platform}: removed {rejected} visually unrelated images")
                platform_processed = sum(
                    1
                    for candidate in manifest.candidates
                    if candidate.platform == platform and candidate.local_processed_path
                )
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
    save_manifest(manifest, run_dir)
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
        original_path = Path(candidate.local_original_path) if candidate.local_original_path else await download_image(client, candidate.image_url, run_dir / "originals", candidate.id)
        with Image.open(original_path) as image:
            candidate.width, candidate.height = image.size
        if min(candidate.width or 0, candidate.height or 0) < 240:
            candidate.status_labels.append("visual_mismatch")
            manifest.logs.append(f"{candidate.platform}: rejected too-small image {original_path.name}")
            return False
        if not is_visually_related(reference_path, original_path):
            candidate.status_labels.append("visual_mismatch")
            manifest.logs.append(f"{candidate.platform}: rejected visually unrelated image {original_path.name}")
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
        return True


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
