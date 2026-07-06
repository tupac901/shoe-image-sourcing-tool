import pytest

from PIL import Image

from shoe_image_sourcing.adapters.poizon_visual import (
    PoizonVisualAdapter,
    _prepare_poizon_upload_image,
    extract_poizon_candidates,
)
from shoe_image_sourcing.config import OPTIONAL_PLATFORMS


def test_optional_platforms_include_poizon_visual():
    platform = next((item for item in OPTIONAL_PLATFORMS if item.name == "poizon_visual"), None)

    assert platform is not None
    assert platform.enabled_by_default is False
    assert platform.speed_tier == "deep"


def test_extract_poizon_candidates_from_product_list_response():
    payload = {
        "data": {
            "searchProducts": {
                "data": [
                    {
                        "id": "cw2288-111",
                        "name": "Nike Air Force 1 Low '07 Triple White",
                        "brandLabel": "Nike",
                        "url": "https://poizon.ru/product/cw2288-111",
                        "finalPrice": 7818,
                        "images": [
                            {"url": "https://img.poizon.ru/product-1.avif"},
                            {"url": "https://img.poizon.ru/product-2.avif"},
                        ],
                    }
                ]
            }
        }
    }

    candidates = extract_poizon_candidates(payload, "Nike Air Force 1")

    assert len(candidates) == 2
    assert candidates[0].platform == "poizon_visual"
    assert candidates[0].title == "Nike Air Force 1 Low '07 Triple White | Nike | 7818 RUB"
    assert candidates[0].source_page_url == "https://poizon.ru/product/cw2288-111"
    assert candidates[0].image_url == "https://img.poizon.ru/product-1.avif"


def test_extract_poizon_candidates_marks_sku_search_results():
    payload = {
        "data": {
            "searchProducts": {
                "data": [
                    {
                        "id": "1012c008-103",
                        "name": "ASICS sneaker",
                        "brandLabel": "Asics",
                        "url": "/product/1012c008-103",
                        "images": [{"url": "https://img.poizon.ru/asics.avif"}],
                    }
                ]
            }
        }
    }

    candidates = extract_poizon_candidates(payload, "1012C008-103")

    assert candidates[0].source_page_url == "https://poizon.ru/product/1012c008-103"
    assert "poizon_sku_search_result" in candidates[0].status_labels


def test_extract_poizon_candidates_does_not_treat_model_number_as_sku_search():
    payload = {
        "data": {
            "searchProducts": {
                "data": [
                    {
                        "id": "gel-1130",
                        "name": "Asics Gel 1130",
                        "brandLabel": "Asics",
                        "url": "/product/1201a933-100",
                        "images": [{"url": "https://img.poizon.ru/asics-gel-1130.avif"}],
                    }
                ]
            }
        }
    }

    candidates = extract_poizon_candidates(payload, "ASICS GEL 1130 white silver black")

    assert "poizon_sku_search_result" not in candidates[0].status_labels


@pytest.mark.anyio
async def test_poizon_visual_adapter_search_uses_graphql(monkeypatch):
    payload = {
        "data": {
            "searchProducts": {
                "data": [
                    {
                        "id": "mr530sg",
                        "name": "New Balance 530 White Silver Navy",
                        "brandLabel": "New Balance",
                        "url": "https://poizon.ru/product/mr530sg",
                        "finalPrice": 6459,
                        "images": [{"url": "https://img.poizon.ru/nb-530.avif"}],
                    }
                ]
            }
        }
    }

    async def fake_fetch(self, query: str, limit: int, timeout: float):
        assert query == "New Balance 530"
        assert limit == 6
        return payload

    monkeypatch.setattr(PoizonVisualAdapter, "_fetch_products", fake_fetch)

    candidates = await PoizonVisualAdapter().search("New Balance 530", limit=6)

    assert len(candidates) == 1
    assert candidates[0].image_url == "https://img.poizon.ru/nb-530.avif"


@pytest.mark.anyio
async def test_poizon_visual_adapter_search_by_image_uses_poizon_image_query(monkeypatch, tmp_path):
    image_path = tmp_path / "shoe.jpg"
    image_path.write_bytes(b"fake-image")
    payload = {
        "data": {
            "searchProducts": {
                "data": [
                    {
                        "id": "1021a463-001",
                        "name": "Asics Jog 100T 'Black'",
                        "brandLabel": "Asics",
                        "url": "/product/1021a463-001",
                        "finalPrice": 6010,
                        "images": [{"url": "https://static.poizon.ru/asics-jog.jpg"}],
                    }
                ]
            }
        }
    }

    async def fake_fetch(self, path, limit: int, timeout: float):
        assert path == image_path
        assert limit == 6
        return payload

    monkeypatch.setattr(PoizonVisualAdapter, "_fetch_products_by_image", fake_fetch)

    candidates = await PoizonVisualAdapter().search_by_image(image_path, limit=6)

    assert candidates[0].source_page_url == "https://poizon.ru/product/1021a463-001"
    assert "poizon_visual_image_search_result" in candidates[0].status_labels


def test_prepare_poizon_upload_image_converts_non_jpeg_to_jpeg(tmp_path):
    source = tmp_path / "shoe.webp"
    Image.new("RGBA", (16, 16), (255, 255, 255, 0)).save(source, "WEBP")

    prepared, should_delete = _prepare_poizon_upload_image(source)

    try:
        assert should_delete
        assert prepared.suffix == ".jpg"
        with Image.open(prepared) as image:
            assert image.format == "JPEG"
            assert image.mode == "RGB"
    finally:
        if should_delete:
            prepared.unlink(missing_ok=True)
