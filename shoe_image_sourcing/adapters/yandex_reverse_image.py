from __future__ import annotations

from hashlib import sha1
from html import unescape
import json
from pathlib import Path
import tempfile
from typing import Any
from urllib.parse import quote_plus, urljoin

import httpx
from PIL import Image

from shoe_image_sourcing.adapters.search_pages import extract_image_results
from shoe_image_sourcing.models import ImageCandidate

from .base import PlatformAdapter


YANDEX_REVERSE_UPLOAD_HOSTS = ("https://yandex.ru/images/search", "https://yandex.com/images/search")
YANDEX_REVERSE_BASE_URL = "https://yandex.ru/images/search"


def extract_yandex_reverse_search_url(payload: dict[str, Any]) -> str:
    for block in payload.get("blocks", []):
        params = block.get("params") or {}
        url = params.get("url") or params.get("cbirUrl")
        if url:
            url = unescape(str(url)).strip()
            if url.startswith(("http://", "https://")):
                return url
            return urljoin(YANDEX_REVERSE_BASE_URL, "?" + url.lstrip("?"))
        cbir_id = params.get("cbirId")
        image_url = params.get("originalImageUrl")
        if cbir_id and image_url:
            return (
                f"{YANDEX_REVERSE_BASE_URL}?rpt=imageview"
                f"&cbir_id={quote_plus(str(cbir_id))}"
                f"&url={quote_plus(str(image_url))}"
            )
    raise ValueError("Yandex reverse image upload response did not include a search URL")


class YandexReverseImageAdapter(PlatformAdapter):
    platform = "yandex_reverse_image"

    def __init__(self, reference_image_path: Path | None):
        self.reference_image_path = reference_image_path

    async def search(self, query: str, limit: int = 12, timeout: float = 8) -> list[ImageCandidate]:
        if self.reference_image_path is None or not self.reference_image_path.exists():
            return [self._fallback_candidate(query, "missing_reference_image")]
        try:
            search_url = await self._upload_reference_image(self.reference_image_path, timeout=timeout)
            html = await self._fetch_results_page(search_url, timeout=timeout)
            results = extract_image_results(html, search_url, limit=limit)
        except Exception as exc:
            return [self._fallback_candidate(query, f"reverse_search_failed:{exc}")]
        if not results:
            return [self._fallback_candidate(query, "reverse_search_no_images")]

        candidates = []
        for result in results:
            image_url = result["image_url"]
            candidate_id = sha1(f"{self.platform}:{query}:{image_url}".encode("utf-8")).hexdigest()[:16]
            candidates.append(
                ImageCandidate(
                    id=candidate_id,
                    platform=self.platform,
                    source_page_url=result.get("source_page_url") or search_url,
                    image_url=image_url,
                    title=result.get("title") or f"{self.platform} image for {query}",
                )
            )
        return candidates

    async def _upload_reference_image(self, image_path: Path, timeout: float) -> str:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        }
        params = {"rpt": "imageview", "format": "json", "request": '{"blocks":[{"block":"b-page_type_search-by-image__link"}]}'}
        errors = []
        for upload_url in YANDEX_REVERSE_UPLOAD_HOSTS:
            try:
                upload_path, remove_after = _prepare_yandex_upload_image(image_path)
                try:
                    with upload_path.open("rb") as image_file:
                        files = {"upfile": (upload_path.name, image_file, _content_type_for(upload_path))}
                        async with httpx.AsyncClient(headers={**headers, "Referer": upload_url}, follow_redirects=True, timeout=timeout) as client:
                            response = await client.post(upload_url, params=params, files=files)
                            response.raise_for_status()
                            if response.text.lstrip().startswith("<"):
                                raise ValueError("Yandex returned an HTML interstitial instead of JSON")
                            return extract_yandex_reverse_search_url(response.json())
                finally:
                    if remove_after:
                        upload_path.unlink(missing_ok=True)
            except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
                errors.append(f"{upload_url}: {exc}")
        raise ValueError("; ".join(errors))

    async def _fetch_results_page(self, search_url: str, timeout: float) -> str:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        }
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=timeout) as client:
            response = await client.get(search_url)
            response.raise_for_status()
            return response.text

    def _fallback_candidate(self, query: str, reason: str) -> ImageCandidate:
        candidate_id = sha1(f"{self.platform}:{query}:{reason}".encode("utf-8")).hexdigest()[:16]
        return ImageCandidate(
            id=candidate_id,
            platform=self.platform,
            source_page_url=YANDEX_REVERSE_BASE_URL,
            image_url="",
            title=f"Yandex reverse image search for {query}",
            status_labels=["search_page_only", "fetch_skipped_or_blocked", reason],
        )


def _content_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "application/octet-stream"


def _prepare_yandex_upload_image(path: Path) -> tuple[Path, bool]:
    if _content_type_for(path) != "application/octet-stream":
        return path, False
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    temp_path = Path(temp_file.name)
    temp_file.close()
    try:
        with Image.open(path) as image:
            image.convert("RGB").save(temp_path, "JPEG", quality=94)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return temp_path, True
