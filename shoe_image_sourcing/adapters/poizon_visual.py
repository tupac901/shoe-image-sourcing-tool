from __future__ import annotations

from hashlib import sha1
from typing import Any

import httpx

from shoe_image_sourcing.models import ImageCandidate

from .base import PlatformAdapter


POIZON_GRAPHQL_URL = "https://poizon.ru/graphql"
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


def extract_poizon_candidates(payload: dict[str, Any], query: str) -> list[ImageCandidate]:
    products = (((payload.get("data") or {}).get("searchProducts") or {}).get("data") or [])
    candidates: list[ImageCandidate] = []
    query_has_sku_shape = any(ch.isdigit() for ch in query) and len("".join(ch for ch in query if ch.isalnum())) >= 6
    for product in products:
        product_id = str(product.get("id") or "")
        product_name = str(product.get("name") or "").strip()
        brand = str(product.get("brandLabel") or "").strip()
        price = product.get("finalPrice")
        product_url = str(product.get("url") or "").strip()
        if product_url.startswith("/"):
            product_url = "https://poizon.ru" + product_url
        title_parts = [product_name]
        if brand:
            title_parts.append(brand)
        if price:
            title_parts.append(f"{price} ₽")
        title = " | ".join(part for part in title_parts if part)
        for image in product.get("images") or []:
            image_url = str((image or {}).get("url") or "").strip()
            if not image_url:
                continue
            digest = sha1(f"poizon_visual:{query}:{product_id}:{image_url}".encode("utf-8")).hexdigest()[:16]
            candidates.append(
                ImageCandidate(
                    id=digest,
                    platform="poizon_visual",
                    source_page_url=product_url or "https://poizon.ru/cat/shoes",
                    image_url=image_url,
                    title=title or f"poizon_visual image for {query}",
                    status_labels=[
                        "poizon_product_candidate",
                        *(["poizon_sku_search_result"] if query_has_sku_shape else []),
                    ],
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
            "variables": __import__("json").dumps(variables, ensure_ascii=False),
        }
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Referer": "https://poizon.ru/cat/shoes",
        }
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=timeout) as client:
            response = await client.get(POIZON_GRAPHQL_URL, params=params)
            response.raise_for_status()
            return response.json()

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
