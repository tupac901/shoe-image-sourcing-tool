from pathlib import Path

from shoe_image_sourcing.adapters.search_pages import build_search_url
from shoe_image_sourcing.config import DEFAULT_PLATFORMS, OPTIONAL_PLATFORMS, SUPPORTED_IMAGE_TYPES
from shoe_image_sourcing.models import ProductFacts
from shoe_image_sourcing.query import enrich_product_facts, generate_queries


def test_image_only_page_shows_checked_platforms():
    html = (Path(__file__).resolve().parents[1] / "shoe_image_sourcing" / "static" / "index.html").read_text(encoding="utf-8")

    for platform in ["poizon_visual", "kr_poizon", "wildberries", "ozon"]:
        assert f'value="{platform}" checked' in html


def test_platform_defaults_include_ozon_reference_sources():
    names = {platform.name for platform in DEFAULT_PLATFORMS}
    assert {"wildberries", "yandex_images", "ozon", "ebay", "stockx", "goat"}.issubset(names)


def test_optional_platforms_are_disabled_by_default():
    enabled = {platform.name for platform in OPTIONAL_PLATFORMS if platform.enabled_by_default}
    assert {"poizon_visual", "kr_poizon"}.issubset(enabled)


def test_multi_platform_image_search_defaults_are_enabled():
    default_enabled = {platform.name for platform in DEFAULT_PLATFORMS if platform.enabled_by_default}
    optional_enabled = {platform.name for platform in OPTIONAL_PLATFORMS if platform.enabled_by_default}

    assert {"wildberries", "ozon"}.issubset(default_enabled)
    assert {"poizon_visual", "kr_poizon"}.issubset(optional_enabled)


def test_kr_poizon_search_url_is_supported():
    assert build_search_url("kr_poizon", "Asics Gel Kayano").startswith("https://kr.poizon.com/search?keyword=Asics+Gel+Kayano")


def test_avif_uploads_are_supported():
    assert "image/avif" in SUPPORTED_IMAGE_TYPES


def test_product_facts_normalizes_empty_fields():
    facts = ProductFacts(brand=" Nike ", model="", sku=None, color=" white navy ", keywords="")
    assert facts.brand == "Nike"
    assert facts.model is None
    assert facts.sku is None
    assert facts.color == "white navy"


def test_generate_queries_prioritizes_sku_and_shoe_terms():
    facts = ProductFacts(brand="Nike", model="Air Monarch IV", sku="415445-102", color="White Navy")
    queries = generate_queries(facts)
    assert queries[0] == '"415445-102" "Nike Air Monarch IV" shoe'
    assert queries[1] == "415445-102 Nike Air Monarch IV product images"
    assert queries[2] == "415445-102 Nike Air Monarch IV official product photos"
    assert "Nike Air Monarch IV 415445-102 White Navy shoes" in queries
    assert "Nike Air Monarch IV 415445-102 кроссовки" in queries
    assert "415445-102 Nike shoe product photos" in queries


def test_generate_queries_uses_keywords_when_sku_missing():
    facts = ProductFacts(brand="Nike", keywords="white navy dad shoes")
    queries = generate_queries(facts)
    assert "Nike white navy dad shoes shoes" in queries


def test_enrich_product_facts_from_pasted_product_text():
    text = """
【产品基础信息】
- 品类：男士综合训练休闲老爹鞋 | Nike Air Monarch IV 白藏蓝复古休闲运动鞋
- 俄语名称：Мужские кроссовки для тренировок Nike Air Monarch IV, белый с темно-синей отделкой
- 官方货号：416355-102

【精准规格参数】
Цвет модели：белый + темно-синий + серебристый металлический логотип
"""
    facts = enrich_product_facts(ProductFacts(product_text=text))
    assert facts.brand == "Nike"
    assert facts.sku == "416355-102"
    assert facts.model == "Air Monarch IV"
    assert "белый" in facts.color


def test_enrich_product_facts_reads_common_title_labels():
    text = """
商品标题：Nike Air Monarch IV 男士综合训练休闲老爹鞋，白藏蓝
货号：416355-102
颜色：白藏蓝
"""
    facts = enrich_product_facts(ProductFacts(product_text=text))

    assert facts.brand == "Nike"
    assert facts.sku == "416355-102"
    assert facts.model == "Air Monarch IV"
