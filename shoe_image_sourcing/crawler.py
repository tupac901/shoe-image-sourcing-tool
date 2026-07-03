from __future__ import annotations

from pathlib import Path
from hashlib import sha1

import anyio
import httpx
from better_bing_image_downloader import Bing
from PIL import Image

from .adapters.search_pages import SearchPageAdapter
from .adapters.search_pages import build_search_url
from .config import FAST_PLATFORM_TIMEOUT_SECONDS, IMAGE_DOWNLOAD_TIMEOUT_SECONDS
from .dedupe import group_duplicates
from .image_processing import compute_phash, make_thumbnail, process_to_3x4
from .models import ImageCandidate, RunManifest
from .storage import save_manifest


async def collect_candidates(manifest: RunManifest, run_dir: Path, limit_per_platform: int = 6) -> RunManifest:
    manifest.status = "running"
    manifest.logs.append("crawl started in fast background mode")
    save_manifest(manifest, run_dir)

    for platform in manifest.platforms:
        platform_total = 0
        for query in manifest.queries[:1]:
            try:
                if platform == "bing_images":
                    candidates = await collect_bing_downloader_candidates(query, run_dir, limit_per_platform)
                else:
                    adapter = SearchPageAdapter(platform)
                    candidates = await adapter.search(query, limit=limit_per_platform, timeout=FAST_PLATFORM_TIMEOUT_SECONDS)
                for candidate in candidates:
                    if platform == "ozon" and "competitor_reference_only" not in candidate.status_labels:
                        candidate.status_labels.append("competitor_reference_only")
                manifest.candidates.extend(candidates)
                platform_total += len(candidates)
                manifest.logs.append(f"{platform}: collected {len(candidates)} entries for {query}")
            except Exception as exc:
                manifest.logs.append(f"{platform}: failed for {query}: {exc}")
        manifest.logs.append(f"{platform}: search step done, {platform_total} entries")
        save_manifest(manifest, run_dir)
    await download_and_process_candidates(manifest, run_dir)
    manifest.status = "complete"
    manifest.logs.append("run complete")
    save_manifest(manifest, run_dir)
    return manifest


async def collect_bing_downloader_candidates(query: str, run_dir: Path, limit: int):
    download_dir = run_dir / "originals" / "bing_images"
    download_dir.mkdir(parents=True, exist_ok=True)

    def run_downloader():
        engine = Bing(
            query=query,
            limit=limit,
            output_dir=download_dir,
            timeout=FAST_PLATFORM_TIMEOUT_SECONDS,
            verbose=False,
            name="bing",
            max_workers=4,
            min_dimension=120,
            force_replace=True,
        )
        engine.run()

    await anyio.to_thread.run_sync(run_downloader)

    candidates = []
    for path in sorted(item for item in download_dir.iterdir() if item.is_file()):
        candidate_id = sha1(f"bing_images:{query}:{path.name}".encode("utf-8")).hexdigest()[:16]
        candidates.append(
            ImageCandidate(
                id=candidate_id,
                platform="bing_images",
                source_page_url=build_search_url("bing_images", query),
                image_url="",
                title=f"Bing downloaded image for {query}",
                local_original_path=path.as_posix(),
                status_labels=["open_source_downloader"],
            )
        )
    return candidates


async def download_and_process_candidates(manifest: RunManifest, run_dir: Path) -> None:
    hashes: dict[str, str] = {}
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=IMAGE_DOWNLOAD_TIMEOUT_SECONDS,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"},
    ) as client:
        candidates = [candidate for candidate in manifest.candidates if candidate.image_url or candidate.local_original_path]
        semaphore = anyio.Semaphore(4)

        async def process_one(candidate):
            async with semaphore:
                await download_and_process_one(client, candidate, run_dir, hashes, manifest)

        async with anyio.create_task_group() as task_group:
            for candidate in candidates:
                task_group.start_soon(process_one, candidate)
    group_duplicates(manifest.candidates, hashes)
    save_manifest(manifest, run_dir)


async def download_and_process_one(
    client: httpx.AsyncClient,
    candidate,
    run_dir: Path,
    hashes: dict[str, str],
    manifest: RunManifest,
) -> None:
    if not candidate.image_url and not candidate.local_original_path:
        return
    try:
        original_path = Path(candidate.local_original_path) if candidate.local_original_path else await download_image(client, candidate.image_url, run_dir / "originals", candidate.id)
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
