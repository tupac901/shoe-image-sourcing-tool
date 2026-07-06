from datetime import datetime

import httpx
import pytest
from PIL import Image

import shoe_image_sourcing.crawler as crawler
from shoe_image_sourcing.crawler import (
    candidates_from_downloaded_images,
    download_and_process_one,
    fallback_queries,
    filter_candidates_for_manifest,
    is_textually_relevant,
    platform_queries_for_manifest,
    poizon_visual_direct_reverse_candidates,
    poizon_visual_hint_queries,
    should_accept_candidate_for_manifest,
    should_accept_candidate_match,
    text_relevance_score,
)
from shoe_image_sourcing.models import ImageCandidate, ProductFacts, RunManifest


def _manifest(facts: ProductFacts) -> RunManifest:
    return RunManifest(run_id="test", created_at=datetime.now(), facts=facts, queries=[], platforms=[])


def test_text_relevance_rejects_brand_plus_generic_shoe_when_sku_missing():
    manifest = _manifest(ProductFacts(brand="Nike", model="Air Monarch IV Men's Training Shoe White Navy"))
    candidate = ImageCandidate(
        id="candidate",
        platform="bing_images",
        source_page_url="https://example.com/nike-running-shoes",
        image_url="https://example.com/nike-shoe.jpg",
        title="Nike running shoes for men",
    )

    assert text_relevance_score(candidate, manifest) < 4
    assert not is_textually_relevant(candidate, manifest)


def test_text_relevance_accepts_multiple_distinct_model_tokens_without_sku():
    manifest = _manifest(ProductFacts(brand="Nike", model="Air Monarch IV Men's Training Shoe White Navy"))
    candidate = ImageCandidate(
        id="candidate",
        platform="bing_images",
        source_page_url="https://example.com/nike-air-monarch",
        image_url="https://example.com/nike-air-monarch.jpg",
        title="Nike Air Monarch IV white navy",
    )

    assert text_relevance_score(candidate, manifest) >= 4
    assert is_textually_relevant(candidate, manifest)


def test_fallback_queries_prioritize_sku_brand_model():
    manifest = _manifest(ProductFacts(brand="Nike", model="Air Monarch IV", sku="416355-102", color="White Navy"))

    assert fallback_queries(manifest) == [
        "416355-102 Nike Air Monarch IV",
        "Nike Air Monarch IV",
        "416355-102 shoe",
    ]


def test_downloaded_image_candidates_use_local_files_and_manifest_sources(tmp_path):
    download_dir = tmp_path / "416355-102 Nike Air Monarch IV"
    download_dir.mkdir()
    image_path = download_dir / "fallback_1.jpg"
    Image.new("RGB", (640, 640), "white").save(image_path)
    (download_dir / "_manifest.json").write_text('{"fallback_1.jpg": "https://example.com/product.jpg?x=1&amp;y=2"}', encoding="utf-8")

    candidates = candidates_from_downloaded_images(download_dir, "416355-102 Nike Air Monarch IV")

    assert len(candidates) == 1
    assert candidates[0].platform == "bing_downloader"
    assert candidates[0].local_original_path == image_path.as_posix()
    assert candidates[0].image_url == "https://example.com/product.jpg?x=1&y=2"
    assert candidates[0].title == "bing_downloader image for 416355-102 Nike Air Monarch IV"
    assert "downloaded_image_fallback" in candidates[0].status_labels


def test_downloaded_image_candidate_does_not_get_text_score_from_query_title(tmp_path):
    download_dir = tmp_path / "416355-102 Nike Air Monarch IV"
    download_dir.mkdir()
    image_path = download_dir / "fallback_1.jpg"
    Image.new("RGB", (640, 640), "white").save(image_path)
    (download_dir / "_manifest.json").write_text('{"fallback_1.jpg": "https://example.com/unrelated.jpg"}', encoding="utf-8")
    manifest = _manifest(ProductFacts(brand="Nike", model="Air Monarch IV", sku="416355-102"))

    candidate = candidates_from_downloaded_images(download_dir, "416355-102 Nike Air Monarch IV")[0]

    assert text_relevance_score(candidate, manifest) == 0


def test_match_accepts_high_profile_visual_candidate_without_text_match():
    candidate = ImageCandidate(
        id="candidate",
        platform="bing_images",
        source_page_url="https://www.bing.com/images/search?q=416355-102",
        image_url="https://example.com/white-shoe.jpg",
        title="bing_images image for 416355-102 Nike Air Monarch IV",
    )

    assert should_accept_candidate_match(candidate, text_score=0, visual_score=63, profile_score=90)


def test_match_rejects_weak_visual_candidate_without_text_match():
    candidate = ImageCandidate(
        id="candidate",
        platform="bing_images",
        source_page_url="https://www.bing.com/images/search?q=416355-102",
        image_url="https://example.com/white-object.jpg",
        title="bing_images image for 416355-102 Nike Air Monarch IV",
    )

    assert not should_accept_candidate_match(candidate, text_score=0, visual_score=40, profile_score=90)


def test_poizon_candidate_rejects_wrong_sku_even_when_visually_similar():
    manifest = _manifest(ProductFacts(brand="Asics", model="Novablast 6", sku="1012C008-103"))
    candidate = ImageCandidate(
        id="candidate",
        platform="poizon_visual",
        source_page_url="https://poizon.ru/product/1012b765-6",
        image_url="https://static.poizon.ru/novablast5.jpg",
        title="ASICS NOVABLAST 5 Comfortable Versatile Casual Running Shoes Women's Red | Asics | 11875 ₽",
    )

    assert not should_accept_candidate_for_manifest(candidate, manifest, text_score=8, visual_score=90, profile_score=88, feature_score=80)


def test_poizon_candidate_accepts_exact_sku_match():
    manifest = _manifest(ProductFacts(brand="Asics", model="Novablast 6", sku="1012C008-103"))
    candidate = ImageCandidate(
        id="candidate",
        platform="poizon_visual",
        source_page_url="https://poizon.ru/product/1012c008-103",
        image_url="https://static.poizon.ru/novablast6.jpg",
        title="ASICS Novablast 6 1012C008-103 Red | Asics | 11875 ₽",
    )

    assert should_accept_candidate_for_manifest(candidate, manifest, text_score=16, visual_score=70, profile_score=88, feature_score=40)


def test_poizon_exact_sku_still_requires_visual_match():
    manifest = _manifest(ProductFacts(brand="Asics", model="Novablast 6", sku="1012C008-103"))
    candidate = ImageCandidate(
        id="candidate",
        platform="poizon_visual",
        source_page_url="https://poizon.ru/product/1012c008-103",
        image_url="https://static.poizon.ru/wrong-color.jpg",
        title="ASICS Novablast 6 1012C008-103 Red | Asics | 11875 ₽",
    )

    assert not should_accept_candidate_for_manifest(candidate, manifest, text_score=16, visual_score=55, profile_score=65, feature_score=80)


def test_poizon_visual_fallback_requires_strong_visual_match():
    manifest = _manifest(ProductFacts(brand="Asics", model="Gel NYC", sku="1203A759-104"))
    candidate = ImageCandidate(
        id="candidate",
        platform="poizon_visual",
        source_page_url="https://poizon.ru/product/no-sku",
        image_url="https://static.poizon.ru/similar-color.jpg",
        title="ASICS similar sneaker | Asics | 8721 ₽",
        status_labels=["visual_fallback_without_sku"],
    )

    assert not should_accept_candidate_for_manifest(candidate, manifest, text_score=4, visual_score=93, profile_score=88, feature_score=3)
    assert should_accept_candidate_for_manifest(candidate, manifest, text_score=4, visual_score=96, profile_score=90, feature_score=45)


def test_poizon_exact_sku_uses_visual_profile_when_feature_matching_is_weak():
    manifest = _manifest(ProductFacts(brand="Asics", model="Novablast", sku="1012C008-103"))
    candidate = ImageCandidate(
        id="candidate",
        platform="poizon_visual",
        source_page_url="https://poizon.ru/product/1012c008-103",
        image_url="https://static.poizon.ru/1012c008-103.jpg",
        title="ASICS Novablast 1012C008-103 | Asics",
    )

    assert should_accept_candidate_for_manifest(
        candidate,
        manifest,
        text_score=8,
        visual_score=90,
        profile_score=52,
        feature_score=4,
    )


def test_poizon_sku_search_fallback_uses_visual_profile_when_feature_matching_is_weak():
    manifest = _manifest(ProductFacts(brand="Asics", model="Novablast", sku="1012C008-103"))
    candidate = ImageCandidate(
        id="candidate",
        platform="poizon_visual",
        source_page_url="https://poizon.ru/product/1012c008-103",
        image_url="https://static.poizon.ru/1012c008-103.jpg",
        title="ASICS sneaker | Asics",
        status_labels=["visual_fallback_without_sku", "poizon_sku_search_result"],
    )

    assert should_accept_candidate_for_manifest(
        candidate,
        manifest,
        text_score=0,
        visual_score=90,
        profile_score=52,
        feature_score=4,
    )


def test_poizon_without_sku_rejects_lookalike_with_weak_feature_match():
    manifest = _manifest(ProductFacts(brand="Asics", keywords="GEL 1130 white silver black"))
    candidate = ImageCandidate(
        id="candidate",
        platform="poizon_visual",
        source_page_url="https://poizon.ru/product/1011b109-031",
        image_url="https://static.poizon.ru/gel-kahana-lookalike.jpg",
        title="Asics Gel-Kahana 8 Gray Black Brown | Asics",
    )

    assert not should_accept_candidate_for_manifest(
        candidate,
        manifest,
        text_score=2,
        visual_score=90,
        profile_score=58,
        feature_score=5,
    )


def test_poizon_without_sku_rejects_high_visual_low_feature_match():
    manifest = _manifest(ProductFacts(brand="Asics", keywords="GEL 1130 white silver black"))
    candidate = ImageCandidate(
        id="candidate",
        platform="poizon_visual",
        source_page_url="https://poizon.ru/product/1011b646-101",
        image_url="https://static.poizon.ru/gel-flux-lookalike.jpg",
        title="Asics Gel Flux Cn 'Cream White Black' | Asics",
    )

    assert not should_accept_candidate_for_manifest(
        candidate,
        manifest,
        text_score=2,
        visual_score=100,
        profile_score=69,
        feature_score=8,
    )


def test_poizon_candidates_without_exact_sku_are_filtered_before_download():
    manifest = _manifest(ProductFacts(brand="Asics", model="Jog 100S", sku="1201A967-100"))
    exact = ImageCandidate(
        id="exact",
        platform="poizon_visual",
        source_page_url="https://poizon.ru/product/1201a967-100",
        image_url="https://static.poizon.ru/exact.jpg",
        title="Asics Jog 100S 2E Wide 'White Black' | Asics | 5877 ₽",
    )
    wrong = ImageCandidate(
        id="wrong",
        platform="poizon_visual",
        source_page_url="https://poizon.ru/product/1203A123-001",
        image_url="https://static.poizon.ru/wrong.jpg",
        title="ASICS Jog 100S Cream Feather Grey | Asics | 14804 ₽",
    )

    kept, removed = filter_candidates_for_manifest([exact, wrong], manifest)

    assert kept == [exact]
    assert removed == 1


def test_poizon_visual_hint_candidates_ignore_wrong_user_sku_before_download():
    manifest = _manifest(ProductFacts(brand="Asics", model="GEL-KAYANO 14", sku="1203A161-100"))
    candidate = ImageCandidate(
        id="candidate",
        platform="poizon_visual",
        source_page_url="https://poizon.ru/product/1201a967-100",
        image_url="https://static.poizon.ru/jog-100s.jpg",
        title="Asics Jog 100S 2E Wide 'White Black' | Asics | 5877 ₽",
        status_labels=["poizon_visual_hint_result"],
    )

    kept, removed = filter_candidates_for_manifest([candidate], manifest)

    assert kept == [candidate]
    assert removed == 0


def test_poizon_visual_hint_match_ignores_wrong_user_sku():
    manifest = _manifest(ProductFacts(brand="Asics", model="GEL-KAYANO 14", sku="1203A161-100"))
    candidate = ImageCandidate(
        id="candidate",
        platform="poizon_visual",
        source_page_url="https://poizon.ru/product/1201a967-100",
        image_url="https://static.poizon.ru/jog-100s.jpg",
        title="Asics Jog 100S 2E Wide 'White Black' | Asics | 5877 ₽",
        status_labels=["poizon_visual_hint_result"],
    )

    assert should_accept_candidate_for_manifest(
        candidate,
        manifest,
        text_score=0,
        visual_score=100,
        profile_score=100,
        feature_score=74,
    )


def test_poizon_visual_numeric_hint_accepts_black_shoe_low_feature_match():
    manifest = _manifest(ProductFacts(brand="WrongBrand", model="Wrong Model 999", sku="WRONG-SKU-000"))
    candidate = ImageCandidate(
        id="candidate",
        platform="poizon_visual",
        source_page_url="https://poizon.ru/product/1021a463-001",
        image_url="https://static.poizon.ru/jog-100t-black.jpg",
        title="Asics Jog 100T 'Black' | Asics | 6010 ₽",
        status_labels=["poizon_visual_hint_result", "poizon_visual_numeric_hint"],
    )

    assert should_accept_candidate_for_manifest(
        candidate,
        manifest,
        text_score=0,
        visual_score=100,
        profile_score=93,
        feature_score=6,
    )


def test_poizon_visual_non_numeric_hint_still_rejects_weak_feature_match():
    manifest = _manifest(ProductFacts(brand="WrongBrand", model="Wrong Model 999", sku="WRONG-SKU-000"))
    candidate = ImageCandidate(
        id="candidate",
        platform="poizon_visual",
        source_page_url="https://poizon.ru/product/wrong",
        image_url="https://static.poizon.ru/wrong-black.jpg",
        title="Adidas Terrex Hyperhiker Low Kid Hiking Shoes | Adidas",
        status_labels=["poizon_visual_hint_result"],
    )

    assert not should_accept_candidate_for_manifest(
        candidate,
        manifest,
        text_score=0,
        visual_score=100,
        profile_score=90,
        feature_score=5,
    )


@pytest.mark.anyio
async def test_poizon_visual_hint_download_processing_ignores_wrong_user_sku(tmp_path, monkeypatch):
    monkeypatch.setattr(crawler, "visual_similarity_score", lambda reference, candidate: 100)
    monkeypatch.setattr(crawler, "profile_similarity_score", lambda reference, candidate: 100)
    monkeypatch.setattr(crawler, "orb_similarity_score", lambda reference, candidate: 74)
    manifest = _manifest(ProductFacts(brand="Asics", model="GEL-KAYANO 14", sku="1203A161-100"))
    reference_path = tmp_path / "reference.jpg"
    Image.new("RGB", (640, 640), "white").save(reference_path)
    candidate_path = tmp_path / "candidate.jpg"
    Image.new("RGB", (640, 640), "white").save(candidate_path)
    candidate = ImageCandidate(
        id="candidate",
        platform="poizon_visual",
        source_page_url="https://poizon.ru/product/1201a967-100",
        image_url="https://static.poizon.ru/jog-100s.jpg",
        title="Asics Jog 100S 2E Wide 'White Black' | Asics | 5877 ₽",
        local_original_path=candidate_path.as_posix(),
        status_labels=["poizon_visual_hint_result"],
    )
    run_dir = tmp_path / "run"
    (run_dir / "thumbnails").mkdir(parents=True)
    (run_dir / "processed_3x4").mkdir(parents=True)

    async with httpx.AsyncClient() as client:
        accepted = await download_and_process_one(client, candidate, run_dir, {}, manifest, reference_path)

    assert accepted
    assert candidate.local_processed_path


def test_poizon_candidates_keep_small_visual_fallback_when_no_sku_match():
    manifest = _manifest(ProductFacts(brand="Asics", model="Gel Kayano", sku="1203A759-104"))
    candidates = [
        ImageCandidate(
            id=f"candidate-{index}",
            platform="poizon_visual",
            source_page_url=f"https://poizon.ru/product/no-sku-{index}",
            image_url=f"https://static.poizon.ru/no-sku-{index}.jpg",
            title="ASICS retro sneaker | Asics",
        )
        for index in range(6)
    ]

    kept, removed = filter_candidates_for_manifest(candidates, manifest, visual_fallback_limit=3)

    assert len(kept) == 3
    assert removed == 3
    assert all("visual_fallback_without_sku" in candidate.status_labels for candidate in kept)


def test_poizon_queries_ignore_sku_and_model_without_image_hints():
    manifest = RunManifest(
        run_id="test",
        created_at=datetime.now(),
        facts=ProductFacts(
            brand="Asics",
            model="复古低帮休闲板鞋 | ASICS 米白灰棕拼接复古通勤训练板鞋",
            sku="1203A759-104",
        ),
        queries=['"1203A759-104" "Asics 复古低帮休闲板鞋" shoe'],
        platforms=["poizon_visual"],
    )

    assert platform_queries_for_manifest("poizon_visual", manifest, 8) == []


def test_poizon_queries_ignore_keywords_without_image_hints():
    manifest = RunManifest(
        run_id="test",
        created_at=datetime.now(),
        facts=ProductFacts(
            brand="Asics",
            color="white silver black cream",
            keywords="ASICS white silver black retro running sneaker GEL 1130",
        ),
        queries=["Asics product images", "Asics official product photos", "Asics white silver black cream shoes"],
        platforms=["poizon_visual"],
    )

    assert platform_queries_for_manifest("poizon_visual", manifest, 8) == []


def test_poizon_visual_hint_queries_from_reverse_image_url():
    candidates = [
        ImageCandidate(
            id="hint",
            platform="yandex_reverse_image",
            source_page_url="https://yandex.ru/images/search",
            image_url="https://2app.kicksonfire.com/kofapp/upload/events_master_images/ipad_asics-jog-100s-2e-wide-white-black.png",
            title="",
        )
    ]

    assert poizon_visual_hint_queries(candidates, "Asics") == ["ASICS JOG 100S 2E Wide White Black"]


def test_poizon_visual_hint_queries_do_not_need_user_brand():
    candidates = [
        ImageCandidate(
            id="hint",
            platform="yandex_reverse_image",
            source_page_url="https://example.com/product",
            image_url="https://cdn.example.com/asics-gel-kayano-14-white-red-silver.jpg",
            title="ASICS GEL-KAYANO 14 White Red Silver",
        )
    ]

    assert poizon_visual_hint_queries(candidates) == ["ASICS GEL Kayano 14 White Red Silver"]


def test_poizon_visual_hint_queries_detect_split_brand_tokens():
    candidates = [
        ImageCandidate(
            id="hint",
            platform="yandex_reverse_image",
            source_page_url="https://example.com/product",
            image_url="https://cdn.example.com/new-balance-fuelcell-propel-v5.jpg",
            title="New Balance FuelCell Propel V5 2E Wide Black White",
        )
    ]

    assert poizon_visual_hint_queries(candidates)[0] == "New Balance Fuelcell Propel V5 2E Wide Black White"


def test_poizon_visual_direct_reverse_candidates_keep_poizon_images_only():
    candidates = [
        ImageCandidate(
            id="poizon",
            platform="yandex_reverse_image",
            source_page_url="https://yandex.ru/images/search",
            image_url="https://cdn.poizon.com/pro-img/origin-img/20251209/example.jpg",
            title="yandex_reverse_image image for reference image",
        ),
        ImageCandidate(
            id="other",
            platform="yandex_reverse_image",
            source_page_url="https://yandex.ru/images/search",
            image_url="https://example.com/other.jpg",
            title="Other image",
        ),
    ]

    direct = poizon_visual_direct_reverse_candidates(candidates)

    assert len(direct) == 1
    assert direct[0].platform == "poizon_visual"
    assert direct[0].image_url == "https://cdn.poizon.com/pro-img/origin-img/20251209/example.jpg"
    assert "poizon_visual_hint_result" in direct[0].status_labels
    assert "poizon_direct_reverse_image" in direct[0].status_labels
