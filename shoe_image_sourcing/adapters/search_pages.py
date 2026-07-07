from __future__ import annotations

from hashlib import sha1
import json
import re
from html import unescape
from urllib.parse import urljoin
from urllib.parse import quote_plus

import httpx

from shoe_image_sourcing.models import ImageCandidate

from .base import PlatformAdapter


SEARCH_PATTERNS = {
    "bing_images": "https://www.bing.com/images/search?q={query}",
    "wildberries": "https://www.wildberries.ru/catalog/0/search.aspx?search={query}",
    "kr_poizon": "https://kr.poizon.com/search?keyword={query}",
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

    async def search(self, query: str, limit: int = 12, timeout: float = 6) -> list[ImageCandidate]:
        search_url = build_search_url(self.platform, query)
        try:
            results = await fetch_image_results(search_url, limit=limit, timeout=timeout)
        except Exception as exc:
            results = []
        if not results:
            candidate_id = sha1(f"{self.platform}:{query}".encode("utf-8")).hexdigest()[:16]
            return [
                ImageCandidate(
                    id=candidate_id,
                    platform=self.platform,
                    source_page_url=search_url,
                    image_url="",
                    title=f"Search results for {query}",
                    status_labels=["search_page_only", "fetch_skipped_or_blocked"],
                )
            ]

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


async def fetch_image_results(page_url: str, limit: int = 12, timeout: float = 6) -> list[dict[str, str]]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=timeout) as client:
        response = await client.get(page_url)
        response.raise_for_status()
    return extract_image_results(response.text, str(response.url), limit=limit)


async def fetch_image_urls(page_url: str, limit: int = 12, timeout: float = 6) -> list[str]:
    return [result["image_url"] for result in await fetch_image_results(page_url, limit=limit, timeout=timeout)]


def extract_image_results(html: str, base_url: str, limit: int = 12) -> list[dict[str, str]]:
    if "bing.com/images/" in base_url or "cn.bing.com/images/" in base_url:
        bing_results = extract_bing_image_results(html, base_url, limit)
        if bing_results:
            return bing_results
    if "yandex." in base_url and "/images/search" in base_url:
        yandex_results = extract_yandex_site_results(html, base_url, limit)
        if yandex_results:
            return yandex_results
    return [{"image_url": url, "source_page_url": base_url, "title": ""} for url in extract_image_urls_from_html(html, base_url, limit)]


def extract_bing_image_results(html: str, base_url: str, limit: int = 12) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen = set()
    for match in re.finditer(r'm="(\{.+?\})"', html):
        try:
            item = json.loads(unescape(match.group(1)))
        except Exception:
            continue
        image_url = normalize_image_url(str(item.get("murl") or ""), base_url)
        if not image_url or not is_likely_product_image(image_url) or image_url in seen:
            continue
        seen.add(image_url)
        results.append(
            {
                "image_url": image_url,
                "source_page_url": normalize_image_url(str(item.get("purl") or base_url), base_url),
                "title": unescape(str(item.get("t") or item.get("desc") or "")),
            }
        )
        if len(results) >= limit:
            break
    return results


def extract_yandex_site_results(html: str, base_url: str, limit: int = 12) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in re.finditer(r'<li class="CbirSites-Item".*?</li>', html, flags=re.IGNORECASE | re.DOTALL):
        block = match.group(0)
        links = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>', block, flags=re.IGNORECASE)
        if len(links) < 2:
            continue
        image_url = normalize_image_url(links[0], base_url)
        source_page_url = normalize_image_url(links[1], base_url)
        if not image_url or not source_page_url or not is_likely_product_image(image_url):
            continue
        title_match = re.search(r'<div class="CbirSites-ItemTitle">.*?(<a[^>]+>)(.*?)</a>', block, flags=re.IGNORECASE | re.DOTALL)
        title = ""
        if title_match:
            aria_match = re.search(r'aria-label=["\']([^"\']+)["\']', title_match.group(1), flags=re.IGNORECASE)
            title = aria_match.group(1) if aria_match else re.sub(r"<[^>]+>", " ", title_match.group(2))
        key = (image_url, source_page_url)
        if key in seen:
            continue
        seen.add(key)
        results.append(
            {
                "image_url": image_url,
                "source_page_url": source_page_url,
                "title": " ".join(unescape(title).split()),
            }
        )
        if len(results) >= limit:
            break
    return results


def extract_image_urls_from_html(html: str, base_url: str, limit: int = 12) -> list[str]:
    urls: list[str] = []
    seen = set()
    patterns = [
        r'murl&quot;:&quot;([^&]+)&quot;',
        r'"murl"\s*:\s*"([^"]+)"',
        r'"imgurl"\s*:\s*"([^"]+)"',
        r'imgurl=([^&"\']+)',
        r'<img[^>]+(?:src|data-src|data-original|data-lazy)=["\']([^"\']+)["\']',
        r'"(https?://[^"]+\.(?:jpg|jpeg|png|webp)(?:\?[^"]*)?)"',
    ]
    for pattern in patterns:
        for raw_url in re.findall(pattern, html, flags=re.IGNORECASE):
            url = normalize_image_url(raw_url, base_url)
            if not url or not is_likely_product_image(url):
                continue
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
            if len(urls) >= limit:
                return urls
    return urls


async def fetch_legacy_image_urls(page_url: str, limit: int = 12, timeout: float = 6) -> list[str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=timeout) as client:
        response = await client.get(page_url)
        response.raise_for_status()
    return extract_image_urls_from_html(response.text, str(response.url), limit=limit)


def extract_image_urls(html: str, base_url: str, limit: int = 12) -> list[str]:
    return [result["image_url"] for result in extract_image_results(html, base_url, limit)]


def normalize_image_url(raw_url: str, base_url: str) -> str:
    url = unescape(raw_url).strip().strip("\\")
    if not url or url.startswith("data:"):
        return ""
    url = url.replace("\\/", "/").replace("\\u0026", "&")
    if url.startswith("//"):
        url = "https:" + url
    return urljoin(base_url, url)


def is_likely_product_image(url: str) -> bool:
    lowered = url.lower()
    if not lowered.startswith(("http://", "https://")):
        return False
    if not any(ext in lowered for ext in [".jpg", ".jpeg", ".png", ".webp"]):
        return False
    blocked_fragments = [
        "favicon",
        "logo",
        "sprite",
        "icon",
        "blank",
        "pixel",
        "yastatic.net",
        "google.com/images/branding",
        "gstatic.com",
    ]
    return not any(fragment in lowered for fragment in blocked_fragments)
