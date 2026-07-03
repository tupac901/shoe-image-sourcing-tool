from __future__ import annotations

from pathlib import Path

import httpx
from PIL import Image

from .adapters.search_pages import SearchPageAdapter
from .dedupe import group_duplicates
from .image_processing import compute_phash, make_thumbnail, process_to_3x4
from .models import RunManifest
from .storage import save_manifest


async def collect_candidates(manifest: RunManifest, run_dir: Path, limit_per_platform: int = 12) -> RunManifest:
    manifest.status = "running"
    manifest.logs.append("crawl started")
    for platform in manifest.platforms:
        adapter = SearchPageAdapter(platform)
        for query in manifest.queries[:2]:
            try:
                candidates = await adapter.search(query, limit=limit_per_platform)
                for candidate in candidates:
                    if platform == "ozon" and "competitor_reference_only" not in candidate.status_labels:
                        candidate.status_labels.append("competitor_reference_only")
                manifest.candidates.extend(candidates)
                manifest.logs.append(f"{platform}: collected {len(candidates)} search entries for {query}")
            except Exception as exc:
                manifest.logs.append(f"{platform}: failed for {query}: {exc}")
    await download_and_process_candidates(manifest, run_dir)
    manifest.status = "complete"
    save_manifest(manifest, run_dir)
    return manifest


async def download_and_process_candidates(manifest: RunManifest, run_dir: Path) -> None:
    hashes: dict[str, str] = {}
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=15,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"},
    ) as client:
        for candidate in manifest.candidates:
            if not candidate.image_url:
                continue
            try:
                original_path = await download_image(client, candidate.image_url, run_dir / "originals", candidate.id)
                with Image.open(original_path) as image:
                    candidate.width, candidate.height = image.size
                thumb_path = run_dir / "thumbnails" / f"{candidate.id}.jpg"
                processed_path = run_dir / "processed_3x4" / f"{candidate.id}.jpg"
                make_thumbnail(original_path, thumb_path)
                process_to_3x4(original_path, processed_path)
                candidate.local_original_path = original_path.as_posix()
                candidate.local_thumbnail_path = thumb_path.as_posix()
                candidate.local_processed_path = processed_path.as_posix()
                hashes[candidate.id] = compute_phash(original_path)
            except Exception as exc:
                candidate.status_labels.append("download_failed")
                manifest.logs.append(f"{candidate.platform}: image download failed {candidate.image_url}: {exc}")
    group_duplicates(manifest.candidates, hashes)


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
