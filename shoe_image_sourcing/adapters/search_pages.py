from __future__ import annotations

from hashlib import sha1
import re
from html import unescape
from urllib.parse import urljoin
from urllib.parse import quote_plus

import httpx

from shoe_image_sourcing.models import ImageCandidate

from .base import PlatformAdapter


SEARCH_PATTERNS = {
    "wildberries": "https://www.wildberries.ru/catalog/0/search.aspx?search={query}",
    "yandex_images": "https://yandex.com/images/search?text={query}",
    "ozon": "https://www.ozon.ru/search/?text={query}",
    "ebay": "https://www.ebay.com/sch/i.html?_nkw={query}",
    "official": "https://www.google.com/search?tbm=isch&q={query}+official+product+images",
    "lamoda": "https://www.lamoda.ru/catalogsearch/result/?q={query}",
    "avito": "https://www.avito.ru/all?q={query}",
    "stockx": "https://stockx.com/search?s={query}",
    "goat": "https://www.goat.com/search?query={query}",
    "amazon": "https://www.amazon.com/s?k={query}",
    "aliexpress": "https://www.aliexpress.com/wholesale?SearchText={query}",
    "farfetch": "https://www.farfetch.com/search?q={query}",
    "megamarket": "https://megamarket.ru/catalog/?q={query}",
    "kazanexpress": "https://kazanexpress.ru/search?query={query}",
}


def build_search_url(platform: str, query: str) -> str:
    pattern = SEARCH_PATTERNS[platform]
    return pattern.format(query=quote_plus(query))


class SearchPageAdapter(PlatformAdapter):
    def __init__(self, platform: str):
        self.platform = platform

    async def search(self, query: str, limit: int = 12) -> list[ImageCandidate]:
        search_url = build_search_url(self.platform, query)
        try:
            image_urls = await fetch_image_urls(search_url, limit=limit)
        except Exception:
            image_urls = []
        if not image_urls:
            candidate_id = sha1(f"{self.platform}:{query}".encode("utf-8")).hexdigest()[:16]
            return [
                ImageCandidate(
                    id=candidate_id,
                    platform=self.platform,
                    source_page_url=search_url,
                    image_url="",
                    title=f"Search results for {query}",
                    status_labels=["search_page_only"],
                )
            ]

        candidates = []
        for image_url in image_urls:
            candidate_id = sha1(f"{self.platform}:{query}:{image_url}".encode("utf-8")).hexdigest()[:16]
            candidates.append(
                ImageCandidate(
                    id=candidate_id,
                    platform=self.platform,
                    source_page_url=search_url,
                    image_url=image_url,
                    title=f"{self.platform} image for {query}",
                )
            )
        return candidates


async def fetch_image_urls(page_url: str, limit: int = 12) -> list[str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=12) as client:
        response = await client.get(page_url)
        response.raise_for_status()
    return extract_image_urls(response.text, str(response.url), limit=limit)


def extract_image_urls(html: str, base_url: str, limit: int = 12) -> list[str]:
    urls: list[str] = []
    seen = set()
    patterns = [
        r'<img[^>]+(?:src|data-src|data-original|data-lazy)=["\']([^"\']+)["\']',
        r'"(https?://[^"]+\.(?:jpg|jpeg|png|webp)(?:\?[^"]*)?)"',
    ]
    for pattern in patterns:
        for raw_url in re.findall(pattern, html, flags=re.IGNORECASE):
            url = unescape(raw_url).strip()
            if not url or url.startswith("data:"):
                continue
            if url.startswith("//"):
                url = "https:" + url
            url = urljoin(base_url, url)
            lowered = url.lower()
            if not any(ext in lowered for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                continue
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
            if len(urls) >= limit:
                return urls
    return urls
