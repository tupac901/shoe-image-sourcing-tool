import pytest

from datetime import datetime
from PIL import Image

from shoe_image_sourcing.adapters.poizon_visual import (
    PoizonVisualAdapter,
    _prepare_poizon_upload_image,
    extract_poizon_candidates,
)
from shoe_image_sourcing.config import OPTIONAL_PLATFORMS
from shoe_image_sourcing.crawler import (
    is_poizon_visual_low_feature_match,
    should_accept_candidate_for_manifest,
)
from shoe_image_sourcing.models import ProductFacts, RunManifest
from shoe_image_sourcing.image_processing import crop_subject_for_matching


def test_optional_platforms_include_poizon_visual():
    platform = next((item for item in OPTIONAL_PLATFORMS if item.name == "poizon_visual"), None)

    assert platform is not None
    assert platform.enabled_by_default is True
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


@pytest.mark.parametrize(
    ("suffix", "format_name"),
    [
        (".jpg", "JPEG"),
        (".png", "PNG"),
        (".webp", "WEBP"),
        (".avif", "AVIF"),
    ],
)
def test_prepare_poizon_upload_image_always_reencodes_to_jpeg(tmp_path, suffix, format_name):
    source = tmp_path / f"shoe{suffix}"
    image = Image.new("RGBA", (16, 16), (255, 255, 255, 0))
    if format_name == "JPEG":
        image = image.convert("RGB")
    image.save(source, format_name)

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


def test_crop_subject_for_matching_removes_screenshot_frame():
    image = Image.new("RGB", (1000, 700), (232, 232, 232))
    canvas = Image.new("RGB", (760, 460), "white")
    # Product-like brown shoe body.
    for x in range(190, 570):
        for y in range(210, 310):
            canvas.putpixel((x, y), (105, 82, 47))
    for x in range(160, 610):
        for y in range(300, 335):
            canvas.putpixel((x, y), (74, 58, 34))
    # Pale UI arrows that should not dominate the crop.
    for x in range(620, 690):
        for y in range(340, 390):
            canvas.putpixel((x, y), (236, 236, 236))
    image.paste(canvas, (120, 80))

    cropped = crop_subject_for_matching(image)

    assert cropped.width < 620
    assert cropped.height < 260


@pytest.mark.parametrize(
    ("profile_score", "feature_score"),
    [
        (46, 3),
        (66, 2),
    ],
)
def test_poizon_image_search_rejects_low_feature_shape_only_match(profile_score, feature_score):
    payload = {
        "data": {
            "searchProducts": {
                "data": [
                    {
                        "id": "example",
                        "name": "Poizon visual match",
                        "brandLabel": "Brand",
                        "url": "/product/example",
                        "images": [{"url": "https://img.poizon.ru/example.jpg"}],
                    }
                ]
            }
        }
    }
    candidate = extract_poizon_candidates(payload, "uploaded image")[0]
    manifest = RunManifest(
        run_id="test",
        created_at=datetime(2026, 7, 6),
        facts=ProductFacts(),
        queries=[],
        platforms=["poizon_visual"],
    )

    assert not should_accept_candidate_for_manifest(
        candidate,
        manifest,
        text_score=0,
        visual_score=90,
        profile_score=profile_score,
        feature_score=feature_score,
    )
    assert is_poizon_visual_low_feature_match(
        candidate,
        visual_score=90,
        profile_score=profile_score,
        feature_score=feature_score,
    )


def test_poizon_image_search_accepts_strong_feature_match_with_screenshot_crop():
    payload = {
        "data": {
            "searchProducts": {
                "data": [
                    {
                        "id": "sf44112407",
                        "name": "Safiya ankle boots",
                        "brandLabel": "Safiya",
                        "url": "/product/sf44112407",
                        "images": [{"url": "https://img.poizon.ru/safiya.jpg"}],
                    }
                ]
            }
        }
    }
    candidate = extract_poizon_candidates(payload, "uploaded image")[0]
    manifest = RunManifest(
        run_id="test",
        created_at=datetime(2026, 7, 6),
        facts=ProductFacts(),
        queries=[],
        platforms=["poizon_visual"],
    )

    assert should_accept_candidate_for_manifest(
        candidate,
        manifest,
        text_score=0,
        visual_score=63,
        profile_score=93,
        feature_score=60,
    )
