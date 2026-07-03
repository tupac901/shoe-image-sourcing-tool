from shoe_image_sourcing.config import DEFAULT_PLATFORMS, OPTIONAL_PLATFORMS
from shoe_image_sourcing.models import ProductFacts
from shoe_image_sourcing.query import generate_queries


def test_platform_defaults_include_ozon_reference_sources():
    names = {platform.name for platform in DEFAULT_PLATFORMS}
    assert {"wildberries", "yandex_images", "ozon", "ebay", "stockx", "goat"}.issubset(names)


def test_optional_platforms_are_disabled_by_default():
    assert all(not platform.enabled_by_default for platform in OPTIONAL_PLATFORMS)


def test_product_facts_normalizes_empty_fields():
    facts = ProductFacts(brand=" Nike ", model="", sku=None, color=" white navy ", keywords="")
    assert facts.brand == "Nike"
    assert facts.model is None
    assert facts.sku is None
    assert facts.color == "white navy"


def test_generate_queries_prioritizes_sku_and_shoe_terms():
    facts = ProductFacts(brand="Nike", model="Air Monarch IV", sku="415445-102", color="White Navy")
    queries = generate_queries(facts)
    assert queries[0] == "Nike Air Monarch IV 415445-102 White Navy shoes"
    assert "Nike Air Monarch IV 415445-102 кроссовки" in queries
    assert "415445-102 Nike shoe product photos" in queries


def test_generate_queries_uses_keywords_when_sku_missing():
    facts = ProductFacts(brand="Nike", keywords="white navy dad shoes")
    queries = generate_queries(facts)
    assert "Nike white navy dad shoes shoes" in queries
