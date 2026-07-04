from datetime import datetime

from shoe_image_sourcing.crawler import is_textually_relevant, text_relevance_score
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
