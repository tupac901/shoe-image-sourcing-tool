from datetime import datetime

from PIL import Image

from shoe_image_sourcing.crawler import candidates_from_downloaded_images, fallback_queries, is_textually_relevant, text_relevance_score
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
    assert "downloaded_image_fallback" in candidates[0].status_labels
