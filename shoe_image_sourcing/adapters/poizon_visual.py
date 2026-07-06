from __future__ import annotations

from hashlib import sha1
import json
from pathlib import Path
import re
import tempfile
from typing import Any

import httpx
from PIL import Image

from shoe_image_sourcing import image_formats  # noqa: F401
from shoe_image_sourcing.models import ImageCandidate

from .base import PlatformAdapter


POIZON_GRAPHQL_URL = "https://poizon.ru/graphql"
SKU_QUERY_PATTERN = re.compile(r"\b[A-Z0-9]{3,}-[A-Z0-9]{2,}\b", re.I)
PRODUCT_LIST_QUERY = """
query getProductList($search:String,$filters:ProductFiltersInput,$sort:ProductSortInput,$first:Int!,$page:Int){
  searchProducts(search:$search filters:$filters sort:$sort first:$first page:$page){
    data{
      id
      name
      brandLabel
      url
      finalPrice
      images{id url}
    }
  }
}
"""
IMAGE_SEARCH_QUERY = """
query imageSearch($searchImage: Upload, $first: Int!, $page: Int) {
  searchProducts(searchImage: $searchImage, first: $first, page: $page) {
    searchImageHash
    productId
    data {
      id
      spuId
      name
      model
      brandLabel
      url
      urlKey
      availability
      finalPrice
      images { id url path propertyValueId }
    }
  }
}
"""


def _headers(timeout_referer: str = "https://poizon.ru/cat/shoes") -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Origin": "https://poizon.ru",
        "Referer": timeout_referer,
    }


def _poizon_url(value: str) -> str:
    value = (value or "").strip()
    if value.startswith("/"):
        return "https://poizon.ru" + value
    return value


def _prepare_poizon_upload_image(path: Path) -> tuple[Path, bool]:
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    temp_path = Path(temp_file.name)
    temp_file.close()
    try:
        with Image.open(path) as image:
            image = image.convert("RGBA")
            background = Image.new("RGBA", image.size, "WHITE")
            background.alpha_composite(image)
            background.convert("RGB").save(temp_path, "JPEG", quality=94)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return temp_path, True


def extract_poizon_candidates(payload: dict[str, Any], query: str) -> list[ImageCandidate]:
    products = (((payload.get("data") or {}).get("searchProducts") or {}).get("data") or [])
    candidates: list[ImageCandidate] = []
    query_has_sku_shape = bool(SKU_QUERY_PATTERN.search(query))
    image_search = query == "uploaded image"
    for product in products:
        product_id = str(product.get("id") or "")
        product_name = str(product.get("name") or "").strip()
        brand = str(product.get("brandLabel") or "").strip()
        price = product.get("finalPrice")
        product_url = _poizon_url(str(product.get("url") or "").strip())
        title_parts = [product_name]
        if brand:
            title_parts.append(brand)
        if price:
            title_parts.append(f"{price} RUB")
        title = " | ".join(part for part in title_parts if part)
        for image in product.get("images") or []:
            image_url = str((image or {}).get("url") or "").strip()
            if not image_url:
                continue
            digest = sha1(f"poizon_visual:{query}:{product_id}:{image_url}".encode("utf-8")).hexdigest()[:16]
            labels = [
                "poizon_product_candidate",
                *(["poizon_sku_search_result"] if query_has_sku_shape else []),
                *(["poizon_visual_image_search_result", "poizon_visual_hint_result"] if image_search else []),
            ]
            candidates.append(
                ImageCandidate(
                    id=digest,
                    platform="poizon_visual",
                    source_page_url=product_url or "https://poizon.ru/cat/shoes",
                    image_url=image_url,
                    title=title or f"poizon_visual image for {query}",
                    status_labels=labels,
                )
            )
    return candidates


class PoizonVisualAdapter(PlatformAdapter):
    platform = "poizon_visual"

    async def search(self, query: str, limit: int = 12, timeout: float = 8) -> list[ImageCandidate]:
        try:
            payload = await self._fetch_products(query, limit=limit, timeout=timeout)
        except Exception as exc:
            return [self._fallback_candidate(query, f"poizon_search_failed:{exc}")]
        candidates = extract_poizon_candidates(payload, query)
        if not candidates:
            return [self._fallback_candidate(query, "poizon_search_no_images")]
        return candidates[: max(limit * 4, limit)]

    async def search_by_image(self, image_path: str | Path, limit: int = 12, timeout: float = 25) -> list[ImageCandidate]:
        try:
            payload = await self._fetch_products_by_image(image_path, limit=limit, timeout=timeout)
        except Exception as exc:
            return [self._fallback_candidate("uploaded image", f"poizon_image_search_failed:{exc}")]
        candidates = extract_poizon_candidates(payload, "uploaded image")
        if not candidates:
            return [self._fallback_candidate("uploaded image", "poizon_image_search_no_images")]
        return candidates[: max(limit * 2, limit)]

    async def _fetch_products(self, query: str, limit: int, timeout: float) -> dict[str, Any]:
        variables = {
            "first": max(1, min(limit, 24)),
            "page": 1,
            "sort": {"views": "DESC"},
            "search": query,
        }
        params = {
            "query": PRODUCT_LIST_QUERY,
            "operationName": "getProductList",
            "variables": json.dumps(variables, ensure_ascii=False),
        }
        headers = _headers()
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=timeout) as client:
            response = await client.get(POIZON_GRAPHQL_URL, params=params)
            response.raise_for_status()
            return response.json()

    async def _fetch_products_by_image(self, image_path: str | Path, limit: int, timeout: float) -> dict[str, Any]:
        path, should_delete = _prepare_poizon_upload_image(Path(image_path))
        operations = {
            "operationName": "imageSearch",
            "variables": {
                "first": max(1, min(limit, 24)),
                "page": 1,
                "searchImage": None,
            },
            "query": IMAGE_SEARCH_QUERY,
        }
        files = {
            "operations": (None, json.dumps(operations, ensure_ascii=False), "application/json"),
            "map": (None, json.dumps({"0": ["variables.searchImage"]}), "application/json"),
            "0": (path.name, path.read_bytes(), "image/jpeg"),
        }
        headers = _headers()
        headers["Apollo-Require-Preflight"] = "true"
        try:
            async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=timeout) as client:
                response = await client.post(POIZON_GRAPHQL_URL, files=files)
                response.raise_for_status()
                payload = response.json()
                if payload.get("errors"):
                    message = str((payload["errors"][0] or {}).get("message") or "poizon image search error")
                    raise RuntimeError(message)
                return payload
        finally:
            if should_delete:
                path.unlink(missing_ok=True)

    def _fallback_candidate(self, query: str, reason: str) -> ImageCandidate:
        digest = sha1(f"poizon_visual:{query}:{reason}".encode("utf-8")).hexdigest()[:16]
        return ImageCandidate(
            id=digest,
            platform=self.platform,
            source_page_url="https://poizon.ru/cat/shoes",
            image_url="",
            title=f"Poizon visual product search for {query}",
            status_labels=["search_page_only", "fetch_skipped_or_blocked", reason],
        )
