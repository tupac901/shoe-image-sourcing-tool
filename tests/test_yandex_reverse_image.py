from pathlib import Path

import pytest
from PIL import Image

from shoe_image_sourcing.adapters.yandex_reverse_image import (
    YandexReverseImageAdapter,
    extract_yandex_reverse_search_url,
)
from shoe_image_sourcing.config import OPTIONAL_PLATFORMS
from shoe_image_sourcing.crawler import collect_candidates, platform_queries_for_manifest
from shoe_image_sourcing.models import ProductFacts, RunManifest


def test_optional_platforms_include_yandex_reverse_image():
    platform = next((item for item in OPTIONAL_PLATFORMS if item.name == "yandex_reverse_image"), None)

    assert platform is not None
    assert platform.enabled_by_default is False
    assert platform.speed_tier == "deep"


def test_extract_yandex_reverse_search_url_from_upload_response():
    payload = {
        "blocks": [
            {
                "params": {
                    "url": "rpt=imageview&cbir_id=12345&url=https%3A%2F%2Favatars.mds.yandex.net%2Fget-images-cbir%2Fabc"
                }
            }
        ]
    }

    assert extract_yandex_reverse_search_url(payload) == (
        "https://yandex.ru/images/search?"
        "rpt=imageview&cbir_id=12345&url=https%3A%2F%2Favatars.mds.yandex.net%2Fget-images-cbir%2Fabc"
    )


def test_extract_yandex_reverse_search_url_from_cbir_fields():
    payload = {
        "blocks": [
            {
                "params": {
                    "originalImageUrl": "https://avatars.mds.yandex.net/get-images-cbir/abc/orig",
                    "cbirId": "12345/abc",
                }
            }
        ]
    }

    assert extract_yandex_reverse_search_url(payload) == (
        "https://yandex.ru/images/search?"
        "rpt=imageview&cbir_id=12345%2Fabc&url=https%3A%2F%2Favatars.mds.yandex.net%2Fget-images-cbir%2Fabc%2Forig"
    )


def test_yandex_reverse_runs_even_without_text_queries():
    manifest = RunManifest(
        run_id="test",
        created_at=__import__("datetime").datetime.now(),
        facts=ProductFacts(brand="Asics", sku="1012C008-103"),
        queries=[],
        platforms=["yandex_reverse_image"],
    )

    assert platform_queries_for_manifest("yandex_reverse_image", manifest, 0) == ["1012C008-103 Asics"]


@pytest.mark.anyio
async def test_yandex_reverse_adapter_extracts_candidates(monkeypatch, tmp_path):
    reference_path = tmp_path / "reference.jpg"
    Image.new("RGB", (320, 420), "white").save(reference_path)
    upload_payload = {
        "blocks": [
            {
                "params": {
                    "url": "rpt=imageview&cbir_id=12345&url=https%3A%2F%2Favatars.mds.yandex.net%2Fget-images-cbir%2Fabc"
                }
            }
        ]
    }
    result_html = """
    <html>
      <body>
        <img src="https://example.com/product-1.jpg" alt="Nike Air Monarch IV">
        <img src="https://example.com/logo.png" alt="logo">
        <img src="https://example.com/product-2.webp" alt="Nike sneaker">
      </body>
    </html>
    """

    async def fake_upload(self, image_path: Path, timeout: float) -> str:
        return extract_yandex_reverse_search_url(upload_payload)

    async def fake_fetch(self, search_url: str, timeout: float) -> str:
        assert "cbir_id=12345" in search_url
        return result_html

    monkeypatch.setattr(YandexReverseImageAdapter, "_upload_reference_image", fake_upload)
    monkeypatch.setattr(YandexReverseImageAdapter, "_fetch_results_page", fake_fetch)

    adapter = YandexReverseImageAdapter(reference_path)
    candidates = await adapter.search("ignored query", limit=2)

    assert [candidate.platform for candidate in candidates] == ["yandex_reverse_image", "yandex_reverse_image"]
    assert [candidate.image_url for candidate in candidates] == [
        "https://example.com/product-1.jpg",
        "https://example.com/product-2.webp",
    ]


@pytest.mark.anyio
async def test_collect_candidates_runs_yandex_reverse_once(monkeypatch, tmp_path):
    run_dir = tmp_path / "run"
    input_dir = run_dir / "input"
    input_dir.mkdir(parents=True)
    Image.new("RGB", (320, 420), "white").save(input_dir / "reference.jpg")
    for dirname in ["originals", "processed_3x4", "thumbnails"]:
        (run_dir / dirname).mkdir()
    manifest = RunManifest(
        run_id="test",
        created_at=__import__("datetime").datetime.now(),
        facts=ProductFacts(brand="Nike", model="Air Monarch IV", sku="416355-102"),
        queries=["query one", "query two", "query three"],
        platforms=["yandex_reverse_image"],
    )
    calls = []

    async def fake_search(self, query: str, limit: int = 12, timeout: float = 8):
        calls.append(query)
        return []

    async def fake_fallback(*args, **kwargs):
        return None

    monkeypatch.setattr(YandexReverseImageAdapter, "search", fake_search)
    monkeypatch.setattr("shoe_image_sourcing.crawler.run_image_downloader_fallback", fake_fallback)

    await collect_candidates(manifest, run_dir)

    assert calls == ["query one"]
