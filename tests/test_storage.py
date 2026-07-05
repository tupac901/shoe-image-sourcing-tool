import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import shoe_image_sourcing.app as app_module
from shoe_image_sourcing.app import app
from shoe_image_sourcing.models import ImageCandidate, ProductFacts
from shoe_image_sourcing.storage import create_run, load_manifest, save_manifest
from shoe_image_sourcing.crawler import collect_candidates, download_and_process_candidates, is_textually_relevant, prune_rejected_candidates


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
    assert any("ozon: search step done" in log for log in result.logs)
    assert all("search_page_only" not in candidate.status_labels for candidate in result.candidates)


@pytest.mark.anyio
async def test_collect_candidates_marks_failed_when_background_step_crashes(monkeypatch, tmp_path):
    manifest, run_dir = create_run(ProductFacts(brand="Asics", model="Jog 100S"), ["Asics Jog 100S"], ["poizon_visual"], tmp_path)
    reference = run_dir / "input" / "reference.jpg"
    Image.new("RGB", (320, 240), "white").save(reference)

    def broken_analysis(_path):
        raise RuntimeError("image decoder crashed")

    monkeypatch.setattr("shoe_image_sourcing.crawler.analyze_image", broken_analysis)

    result = await collect_candidates(manifest, run_dir)
    loaded = load_manifest(run_dir)

    assert result.status == "failed"
    assert loaded.status == "failed"
    assert any("run failed: image decoder crashed" in log for log in loaded.logs)


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


@pytest.mark.anyio
async def test_download_processing_rejects_bing_browser_asset(tmp_path):
    manifest, run_dir = create_run(ProductFacts(brand="Nike", model="Air Monarch IV", sku="416355-102"), ["Nike shoe"], ["bing_images"], tmp_path)
    reference = run_dir / "input" / "reference.jpg"
    shoe_like = Image.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(shoe_like)
    draw.rectangle((40, 110, 360, 190), fill="white", outline="navy", width=6)
    shoe_like.save(reference)

    candidate = ImageCandidate(
        id="bing-logo",
        platform="bing_images",
        source_page_url="https://www.bing.com/images/search?q=416355-102+Nike+Air+Monarch+IV",
        image_url="https://r.bing.com/rp/bOFwJ0yobV6NnXq4XV6y--Iohrc.png",
        title='bing_images image for "416355-102" "Nike Air Monarch IV" shoe',
    )
    manifest.candidates.append(candidate)
    rejected = await download_and_process_candidates(manifest, run_dir, [candidate], {}, reference)

    assert rejected == 1
    assert "visual_mismatch" in candidate.status_labels
    assert candidate.local_processed_path is None


@pytest.mark.anyio
async def test_download_processing_rejects_generic_search_result_without_visual_match(tmp_path):
    manifest, run_dir = create_run(ProductFacts(brand="Nike", model="Air Monarch IV", sku="416355-102"), ["Nike shoe"], ["aliexpress"], tmp_path)
    reference = run_dir / "input" / "reference.jpg"
    shoe_like = Image.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(shoe_like)
    draw.rectangle((30, 130, 370, 185), fill="white", outline="navy", width=6)
    shoe_like.save(reference)

    unrelated = run_dir / "originals" / "cartridge.jpg"
    unrelated.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (400, 500), "gray")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 60, 320, 440), fill="slategray", outline="black", width=8)
    draw.rectangle((125, 105, 275, 190), fill="red")
    image.save(unrelated)

    candidate = ImageCandidate(
        id="generic-bad",
        platform="aliexpress",
        source_page_url="https://www.aliexpress.com/wholesale?SearchText=416355-102+Nike+Air+Monarch+IV",
        image_url="https://example.com/416355-102-nike-air-monarch-iv.jpg",
        title="aliexpress image for 416355-102 Nike Air Monarch IV product images",
        local_original_path=unrelated.as_posix(),
    )
    manifest.candidates.append(candidate)
    rejected = await download_and_process_candidates(manifest, run_dir, [candidate], {}, reference)

    assert rejected == 1
    assert "visual_mismatch" in candidate.status_labels
    assert candidate.local_processed_path is None


def test_prune_rejected_candidates_removes_bad_gallery_cards(tmp_path):
    manifest, _ = create_run(ProductFacts(brand="Nike"), ["Nike shoe"], ["bing_images"], tmp_path)
    good = ImageCandidate(id="good", platform="bing_images", source_page_url="https://example.com/good", image_url="https://example.com/good.jpg")
    bad = ImageCandidate(
        id="bad",
        platform="bing_images",
        source_page_url="https://example.com/meme",
        image_url="https://example.com/meme.jpg",
        status_labels=["visual_mismatch", "text_score_0", "visual_score_40"],
    )
    failed = ImageCandidate(
        id="failed",
        platform="bing_images",
        source_page_url="https://example.com/blocked",
        image_url="https://example.com/blocked.jpg",
        status_labels=["download_failed"],
    )
    manifest.candidates.extend([good, bad, failed])

    assert prune_rejected_candidates(manifest) == 2
    assert manifest.candidates == [good]


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


def test_create_run_returns_reverse_search_links(tmp_path):
    image_path = tmp_path / "shoe.jpg"
    image = Image.new("RGB", (320, 240), "white")
    image.save(image_path)
    client = TestClient(app)
    with image_path.open("rb") as handle:
        response = client.post(
            "/api/runs",
            data={"brand": "Nike", "model": "Air Monarch IV", "sku": "416355-102", "platforms": ""},
            files={"image": ("shoe.jpg", handle, "image/jpeg")},
        )
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    run = client.get(f"/api/runs/{run_id}").json()
    labels = {link["label"] for link in run["reverse_search_links"]}
    assert {"Google Lens", "Bing Visual Search", "Yandex Images"} <= labels


def test_get_run_returns_clear_error_when_manifest_file_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "OUTPUT_ROOT", tmp_path)
    run_dir = tmp_path / "missing-manifest"
    run_dir.mkdir()
    client = TestClient(app)

    response = client.get("/api/runs/missing-manifest")

    assert response.status_code == 404
    assert response.json()["detail"] == "Run manifest missing"


def test_get_run_returns_clear_error_when_manifest_file_is_invalid(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "OUTPUT_ROOT", tmp_path)
    run_dir = tmp_path / "broken-manifest"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text("{broken", encoding="utf-8")
    client = TestClient(app)

    response = client.get("/api/runs/broken-manifest")

    assert response.status_code == 500
    assert response.json()["detail"].startswith("Run manifest unreadable")


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


def test_generic_search_candidate_does_not_gain_text_score(tmp_path):
    manifest, _ = create_run(
        ProductFacts(brand="Nike", model="Air Monarch IV", sku="416355-102"),
        ["Nike shoe"],
        ["amazon"],
        output_root=tmp_path,
    )
    candidate = ImageCandidate(
        id="ad",
        platform="amazon",
        source_page_url="https://www.amazon.com/s?k=416355-102+Nike+Air+Monarch+IV",
        image_url="https://example.com/prime-video-ad.jpg",
        title="amazon image for 416355-102 Nike Air Monarch IV product images",
    )
    assert not is_textually_relevant(candidate, manifest)
