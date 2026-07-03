from shoe_image_sourcing.dedupe import hamming_distance
from shoe_image_sourcing.adapters.search_pages import build_search_url, extract_image_urls


def test_hamming_distance_hex_hashes():
    assert hamming_distance("ffff", "ffff") == 0
    assert hamming_distance("ffff", "0000") == 16


def test_build_search_url_for_known_platforms():
    assert "wildberries.ru" in build_search_url("wildberries", "Nike shoes")
    assert "yandex" in build_search_url("yandex_images", "Nike shoes")
    assert "ozon.ru" in build_search_url("ozon", "Nike shoes")


def test_extract_image_urls_handles_relative_and_protocol_relative_urls():
    html = '''
    <img src="/images/a.jpg">
    <img data-src="//cdn.example.com/b.webp?x=1">
    <img src="data:image/png;base64,abc">
    '''
    urls = extract_image_urls(html, "https://shop.example.com/page", limit=5)
    assert urls == [
        "https://shop.example.com/images/a.jpg",
        "https://cdn.example.com/b.webp?x=1",
    ]
