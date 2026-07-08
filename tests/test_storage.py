import pytest
import anyio
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import shoe_image_sourcing.app as app_module
from shoe_image_sourcing.app import app
from shoe_image_sourcing.models import ImageCandidate, ProductFacts
from shoe_image_sourcing.storage import create_run, load_manifest, save_manifest
from shoe_image_sourcing.crawler import (
    collect_candidates,
    download_and_process_candidates,
    ensure_image_first_platforms,
    extract_duckduckgo_kr_poizon_links,
    is_textually_relevant,
    kr_poizon_product_link_matches_query,
    kr_poizon_queries_from_reverse_candidates,
    marketplace_visual_reverse_candidates,
    ozon_product_candidates_from_image_hints,
    ozon_product_link_matches_query,
    ozon_queries_from_reverse_candidates,
    extract_duckduckgo_ozon_links,
    prune_rejected_candidates,
    should_accept_candidate_for_manifest,
    should_skip_fallback,
)


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
    assert not (run_dir / "manifest.json.tmp").exists()


def test_poizon_visual_does_not_auto_add_yandex_reverse(tmp_path):
    manifest, _ = create_run(ProductFacts(brand="Asics"), ["Asics shoe"], ["poizon_visual"], tmp_path)

    ensure_image_first_platforms(manifest, has_reference_image=True)

    assert manifest.platforms == ["poizon_visual"]


def test_selected_poizon_visual_runs_before_text_platforms(tmp_path):
    manifest, _ = create_run(
        ProductFacts(brand="Asics"),
        ["Asics shoe"],
        ["poizon_visual", "yandex_reverse_image"],
        tmp_path,
    )

    ensure_image_first_platforms(manifest, has_reference_image=True)

    assert manifest.platforms == ["poizon_visual", "yandex_reverse_image"]


def test_marketplace_visual_reverse_candidates_filter_by_product_domain():
    candidates = [
        ImageCandidate(
            id="ozon",
            platform="yandex_reverse_image",
            source_page_url="https://www.ozon.ru/product/kedy-123/",
            image_url="https://ir.ozone.ru/s3/product.jpg",
            title="Ozon shoe",
        ),
        ImageCandidate(
            id="wb",
            platform="yandex_reverse_image",
            source_page_url="https://www.wildberries.ru/catalog/123/detail.aspx",
            image_url="https://images.wbstatic.net/product.jpg",
            title="WB shoe",
        ),
        ImageCandidate(
            id="search",
            platform="yandex_reverse_image",
            source_page_url="https://www.ozon.ru/search/?text=shoe",
            image_url="https://ir.ozone.ru/s3/search.jpg",
            title="Search page",
        ),
    ]

    ozon = marketplace_visual_reverse_candidates(candidates, "ozon")
    wildberries = marketplace_visual_reverse_candidates(candidates, "wildberries")

    assert [candidate.source_page_url for candidate in ozon] == ["https://www.ozon.ru/product/kedy-123/"]
    assert "image_reverse_product_candidate" in ozon[0].status_labels
    assert [candidate.source_page_url for candidate in wildberries] == ["https://www.wildberries.ru/catalog/123/detail.aspx"]


def test_marketplace_reverse_candidate_accepts_high_visual_mid_profile_match(tmp_path):
    manifest, _ = create_run(ProductFacts(), ["shoe product"], ["wildberries"], tmp_path)
    candidate = ImageCandidate(
        id="wb-visual",
        platform="wildberries",
        source_page_url="https://www.wildberries.ru/catalog/1136838209/detail.aspx",
        image_url="https://images.wbstatic.net/product.webp",
        status_labels=["image_reverse_product_candidate", "wildberries_visual_reverse_result"],
    )

    assert should_accept_candidate_for_manifest(
        candidate,
        manifest,
        text_score=0,
        visual_score=90,
        profile_score=70,
        feature_score=12,
    )


def test_extract_duckduckgo_kr_poizon_links_unwraps_result_urls():
    html = """
    <a class="result__url" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fkr.poizon.com%2Fproduct%2Fnike-ja-morant-3-rebound-grip-basketball-shoes-men-s-8300070295959421&rut=abc">
      kr.poizon.com/product/nike-ja-morant-3-rebound-grip-basketball-shoes-men-s-8300070295959421
    </a>
    """

    assert extract_duckduckgo_kr_poizon_links(html) == [
        "https://kr.poizon.com/product/nike-ja-morant-3-rebound-grip-basketball-shoes-men-s-8300070295959421"
    ]


def test_kr_poizon_queries_from_reverse_candidates_uses_image_hint_titles():
    candidates = [
        ImageCandidate(
            id="hint",
            platform="yandex_reverse_image",
            source_page_url="https://cdek.shopping/p/30722062/basketbol-nye-krossovki-ja-morant-3-grip-rebound",
            image_url="https://example.com/ja3.webp",
            title="Баскетбольные кроссовки Ja Morant 3 Grip Rebound мужские Nike, зеленый купить выгодно",
        )
    ]

    queries = kr_poizon_queries_from_reverse_candidates(candidates)

    assert queries
    assert "Nike Ja 3 Grip Rebound" in queries
    assert "купить" not in queries[0].lower()


def test_kr_poizon_product_link_must_match_image_hint_identity():
    assert kr_poizon_product_link_matches_query(
        "https://kr.poizon.com/product/nike-ja-morant-3-rebound-grip-basketball-shoes-men-s-8300070295959421",
        "Nike Ja 3 Grip Rebound",
    )
    assert not kr_poizon_product_link_matches_query(
        "https://kr.poizon.com/product/bandai-hg-1-144-extraordinary-strike-freedom-gundam-seed-model-kits-596532848",
        "Nike Ja 3 Grip Rebound",
    )
    assert not kr_poizon_product_link_matches_query(
        "https://kr.poizon.com/product/8300075895566453",
        "Nike Ja 3 Grip Rebound",
    )


def test_ozon_queries_from_reverse_candidates_uses_image_hint_titles():
    candidates = [
        ImageCandidate(
            id="hint",
            platform="yandex_reverse_image",
            source_page_url="https://poizon.ru/product/1203a161-100team1954",
            image_url="https://example.com/kayano.webp",
            title="ASICS GEL-KAYANO 14 Cream Grey running sneakers Ozon",
        )
    ]

    queries = ozon_queries_from_reverse_candidates(candidates)

    assert queries
    assert queries[0] == "ASICS GEL-KAYANO 14 Cream Grey"
    assert "ASICS GEL-KAYANO 14" in queries


def test_extract_duckduckgo_ozon_links_unwraps_product_urls():
    html = """
    <a class="result__url" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.ozon.ru%2Fproduct%2Fkrossovki-asics-gel-kayano-14-1203a161-100-1234567890%2F&rut=abc">
      www.ozon.ru/product/krossovki-asics-gel-kayano-14-1203a161-100-1234567890/
    </a>
    <a href="https://www.ozon.ru/search/?text=asics">search page</a>
    """

    assert extract_duckduckgo_ozon_links(html) == [
        "https://www.ozon.ru/product/krossovki-asics-gel-kayano-14-1203a161-100-1234567890/"
    ]


def test_ozon_product_link_must_match_image_hint_identity():
    assert ozon_product_link_matches_query(
        "https://ozon.by/product/krossovki-asics-gel-kayano-14-3052551979/",
        "ASICS GEL-KAYANO 14 Cream Grey",
    )
    assert not ozon_product_link_matches_query(
        "https://www.ozon.ru/product/zont-polnyy-avtomat-4848307190/",
        "ASICS GEL-KAYANO 14 Cream Grey",
    )


def test_ozon_product_candidates_from_image_hints_keeps_image_source(monkeypatch):
    candidates = [
        ImageCandidate(
            id="hint",
            platform="yandex_reverse_image",
            source_page_url="https://poizon.ru/product/1203a161-100team1954",
            image_url="https://example.com/kayano.webp",
            title="ASICS GEL-KAYANO 14 Cream Grey running sneakers",
        )
    ]

    async def fake_search(_queries, limit=6, timeout=8):
        return ["https://www.ozon.ru/product/krossovki-asics-gel-kayano-14-1203a161-100-1234567890/"], ["ok"]

    monkeypatch.setattr("shoe_image_sourcing.crawler.search_ozon_product_links_from_queries", fake_search)

    result, diagnostics = anyio.run(ozon_product_candidates_from_image_hints, candidates)

    assert diagnostics == ["ok"]
    assert result[0].platform == "ozon"
    assert result[0].source_page_url == "https://www.ozon.ru/product/krossovki-asics-gel-kayano-14-1203a161-100-1234567890/"
    assert result[0].image_url == "https://example.com/kayano.webp"
    assert "ozon_site_search_from_image" in result[0].status_labels


def test_image_first_skips_bing_fallback_after_reverse_matches(tmp_path):
    manifest, _ = create_run(ProductFacts(brand="Asics"), ["Asics shoe"], ["yandex_reverse_image", "poizon_visual"], tmp_path)
    for index in range(3):
        manifest.candidates.append(
            ImageCandidate(
                id=f"reverse-{index}",
                platform="yandex_reverse_image",
                source_page_url="https://yandex.ru/images/search",
                image_url=f"https://example.com/{index}.jpg",
                local_processed_path=f"processed/{index}.jpg",
            )
        )

    assert should_skip_fallback(manifest)


@pytest.mark.anyio
async def test_collect_candidates_marks_ozon_reference(tmp_path):
    manifest, run_dir = create_run(ProductFacts(brand="Nike"), ["Nike shoes"], ["ozon"], tmp_path)
    result = await collect_candidates(manifest, run_dir)
    assert result.status == "complete"
    assert any("ozon: search step done" in log for log in result.logs)
    assert any("search_page_only" in candidate.status_labels for candidate in result.candidates)
    assert all(candidate.platform == "ozon" for candidate in result.candidates)


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


@pytest.mark.anyio
async def test_poizon_wrong_sku_candidate_is_rejected_before_download(tmp_path):
    manifest, run_dir = create_run(ProductFacts(brand="Asics", model="Jog 100S", sku="1201A967-100"), ["Asics Jog 100S"], ["poizon_visual"], tmp_path)
    reference = run_dir / "input" / "reference.jpg"
    Image.new("RGB", (400, 300), "white").save(reference)

    class FailingClient:
        async def get(self, _url):
            raise AssertionError("wrong-SKU Poizon images should not be downloaded")

    candidate = ImageCandidate(
        id="wrong-sku",
        platform="poizon_visual",
        source_page_url="https://poizon.ru/product/1203A123-001",
        image_url="https://static.poizon.ru/wrong.jpg",
        title="ASICS Jog 100S Cream Feather Grey | Asics | 14804 ₽",
    )

    from shoe_image_sourcing.crawler import download_and_process_one

    accepted = await download_and_process_one(FailingClient(), candidate, run_dir, {}, manifest, reference)

    assert not accepted
    assert "sku_mismatch" in candidate.status_labels
    assert candidate.local_original_path is None


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


def test_create_run_accepts_image_only_and_defaults_to_multi_platforms(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "OUTPUT_ROOT", tmp_path)

    async def fake_collect_candidates(manifest, run_dir, limit_per_platform=6):
        manifest.status = "complete"
        save_manifest(manifest, run_dir)
        return manifest

    monkeypatch.setattr(app_module, "collect_candidates", fake_collect_candidates)
    image_path = tmp_path / "shoe.jpg"
    Image.new("RGB", (320, 240), "white").save(image_path)
    client = TestClient(app)
    with image_path.open("rb") as handle:
        response = client.post(
            "/api/runs",
            files={"image": ("shoe.jpg", handle, "image/jpeg")},
        )

    assert response.status_code == 200
    run_id = response.json()["run_id"]
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["platforms"] == ["poizon_visual", "kr_poizon", "wildberries", "ozon"]
    assert run["facts"]["brand"] is None
    assert run["facts"]["model"] is None
    assert run["facts"]["sku"] is None


@pytest.mark.skip(reason="image-only Poizon Visual no longer requires product facts")
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
