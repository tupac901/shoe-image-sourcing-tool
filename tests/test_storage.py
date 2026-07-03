import pytest
from fastapi.testclient import TestClient

from shoe_image_sourcing.app import app
from shoe_image_sourcing.models import ProductFacts
from shoe_image_sourcing.storage import create_run, load_manifest, save_manifest
from shoe_image_sourcing.crawler import collect_candidates


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
