from shoe_image_sourcing.dedupe import hamming_distance
from shoe_image_sourcing.adapters.search_pages import build_search_url, extract_image_urls


def test_hamming_distance_hex_hashes():
    assert hamming_distance("ffff", "ffff") == 0
    assert hamming_distance("ffff", "0000") == 16


def test_build_search_url_for_known_platforms():
    assert "bing.com" in build_search_url("bing_images", "Nike shoes")
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


def test_extract_image_urls_prefers_real_bing_murl_and_filters_icons():
    html = '''
    <img src="https://yastatic.net/s3/fiji-static/icon.png">
    <a m="{&quot;murl&quot;:&quot;https://static.shihuocdn.cn/admin/imgs/shoe_937x937.jpeg&quot;}"></a>
    <img src="https://example.com/logo.jpg">
    '''
    urls = extract_image_urls(html, "https://www.bing.com/images/search?q=nike", limit=5)
    assert urls == ["https://static.shihuocdn.cn/admin/imgs/shoe_937x937.jpeg"]
