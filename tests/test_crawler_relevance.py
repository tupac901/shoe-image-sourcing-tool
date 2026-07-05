from datetime import datetime

from PIL import Image

from shoe_image_sourcing.crawler import (
    candidates_from_downloaded_images,
    fallback_queries,
    filter_candidates_for_manifest,
    is_textually_relevant,
    platform_queries_for_manifest,
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

    assert not should_accept_candidate_for_manifest(candidate, manifest, text_score=8, visual_score=90, profile_score=88)


def test_poizon_candidate_accepts_exact_sku_match():
    manifest = _manifest(ProductFacts(brand="Asics", model="Novablast 6", sku="1012C008-103"))
    candidate = ImageCandidate(
        id="candidate",
        platform="poizon_visual",
        source_page_url="https://poizon.ru/product/1012c008-103",
        image_url="https://static.poizon.ru/novablast6.jpg",
        title="ASICS Novablast 6 1012C008-103 Red | Asics | 11875 ₽",
    )

    assert should_accept_candidate_for_manifest(candidate, manifest, text_score=16, visual_score=70, profile_score=88)


def test_poizon_exact_sku_still_requires_visual_match():
    manifest = _manifest(ProductFacts(brand="Asics", model="Novablast 6", sku="1012C008-103"))
    candidate = ImageCandidate(
        id="candidate",
        platform="poizon_visual",
        source_page_url="https://poizon.ru/product/1012c008-103",
        image_url="https://static.poizon.ru/wrong-color.jpg",
        title="ASICS Novablast 6 1012C008-103 Red | Asics | 11875 ₽",
    )

    assert not should_accept_candidate_for_manifest(candidate, manifest, text_score=16, visual_score=55, profile_score=65)


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

    assert not should_accept_candidate_for_manifest(candidate, manifest, text_score=4, visual_score=93, profile_score=88)
    assert should_accept_candidate_for_manifest(candidate, manifest, text_score=4, visual_score=96, profile_score=90)


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


def test_poizon_queries_prioritize_clean_sku_over_long_product_text():
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

    assert platform_queries_for_manifest("poizon_visual", manifest, 8) == ["1203A759-104", "Asics 1203A759-104"]
