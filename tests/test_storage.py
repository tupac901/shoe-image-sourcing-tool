import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from shoe_image_sourcing.app import app
from shoe_image_sourcing.models import ImageCandidate, ProductFacts
from shoe_image_sourcing.storage import create_run, load_manifest, save_manifest
from shoe_image_sourcing.crawler import collect_candidates, download_and_process_candidates, is_textually_relevant


def test_create_run_builds_expected_directories(tmp_path):
    manifest, run_dir = create_run(
        facts=ProductFacts(brand="Nike"),
        queries=["Nike shoes"],
        platforms=["ebay"],
        output_root=tmp_path,
    )
    assert run_dir.exists()
    for name in ["input", "originals", "processed_3x4", "thumbnails"]:
        assert (run_dir / name).is_dir()
    assert manifest.status == "created"


def test_manifest_round_trip(tmp_path):
    manifest, run_dir = create_run(ProductFacts(brand="Nike"), ["Nike shoes"], ["ebay"], tmp_path)
    manifest.logs.append("started")
    save_manifest(manifest, run_dir)
    loaded = load_manifest(run_dir)
    assert loaded.run_id == manifest.run_id
    assert loaded.logs == ["started"]


@pytest.mark.anyio
async def test_collect_candidates_marks_ozon_reference(tmp_path):
    manifest, run_dir = create_run(ProductFacts(brand="Nike"), ["Nike shoes"], ["ozon"], tmp_path)
    result = await collect_candidates(manifest, run_dir)
    assert result.status == "complete"
    assert result.candidates
    assert "competitor_reference_only" in result.candidates[0].status_labels


@pytest.mark.anyio
async def test_download_processing_rejects_visual_mismatch(tmp_path):
    manifest, run_dir = create_run(ProductFacts(brand="Nike", model="Air Monarch IV"), ["Nike shoe"], ["bing_images"], tmp_path)
    reference = run_dir / "input" / "reference.jpg"
    shoe_like = Image.new("RGB", (300, 400), "white")
    draw = ImageDraw.Draw(shoe_like)
    draw.ellipse((40, 190, 260, 260), fill="navy")
    draw.rectangle((80, 150, 240, 220), fill="white", outline="navy", width=6)
    shoe_like.save(reference)

    unrelated = run_dir / "originals" / "classroom.jpg"
    unrelated.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (300, 400), "forestgreen")
    draw = ImageDraw.Draw(image)
    for offset in range(0, 300, 30):
        draw.rectangle((offset, 0, offset + 12, 400), fill="orange")
    image.save(unrelated)

    candidate = ImageCandidate(
        id="bad",
        platform="bing_images",
        source_page_url="https://example.com",
        image_url="",
        local_original_path=unrelated.as_posix(),
    )
    manifest.candidates.append(candidate)
    rejected = await download_and_process_candidates(manifest, run_dir, [candidate], {}, reference)

    assert rejected == 1
    assert "visual_mismatch" in candidate.status_labels
    assert candidate.local_processed_path is None


def test_platforms_endpoint_returns_defaults():
    client = TestClient(app)
    response = client.get("/api/platforms")
    assert response.status_code == 200
    data = response.json()
    assert any(platform["name"] == "ozon" for platform in data["default"])


def test_create_run_rejects_brand_only_search(tmp_path):
    image_path = tmp_path / "shoe.jpg"
    image_path.write_bytes(b"not-a-real-image-but-upload-validation-only-checks-content-type")
    client = TestClient(app)
    with image_path.open("rb") as handle:
        response = client.post(
            "/api/runs",
            data={"brand": "Nike"},
            files={"image": ("shoe.jpg", handle, "image/jpeg")},
        )
    assert response.status_code == 400
    assert "型号" in response.json()["detail"]


def test_bing_candidate_must_match_sku_or_model_text(tmp_path):
    manifest, _ = create_run(
        ProductFacts(brand="Nike", model="Air Monarch IV", sku="416355-102"),
        ["Nike shoe"],
        ["bing_images"],
        output_root=tmp_path,
    )
    good = ImageCandidate(
        id="good",
        platform="bing_images",
        source_page_url="https://example.com/nike-air-monarch-iv-416355-102",
        image_url="https://example.com/air-monarch.jpg",
        title="Nike Air Monarch IV White Navy 416355-102",
    )
    bad = ImageCandidate(
        id="bad",
        platform="bing_images",
        source_page_url="https://example.com/pink-dunk",
        image_url="https://example.com/pink-dunk.jpg",
        title="Nike SB Dunk Low pink shoes",
    )
    assert is_textually_relevant(good, manifest)
    assert not is_textually_relevant(bad, manifest)
