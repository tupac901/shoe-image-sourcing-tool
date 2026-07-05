import pytest

from shoe_image_sourcing.adapters.poizon_visual import PoizonVisualAdapter, extract_poizon_candidates
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
    assert candidates[0].title == "Nike Air Force 1 Low '07 Triple White | Nike | 7818 ₽"
    assert candidates[0].source_page_url == "https://poizon.ru/product/cw2288-111"
    assert candidates[0].image_url == "https://img.poizon.ru/product-1.avif"


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
