from pathlib import Path

from .models import PlatformConfig


OUTPUT_ROOT = Path("outputs/shoe_image_sourcing/runs")
MAX_UPLOAD_MB = 8
MAX_IMAGES_PER_RUN = 80
FAST_PLATFORM_TIMEOUT_SECONDS = 6
IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 6
SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/avif"}

DEFAULT_PLATFORMS = [
    PlatformConfig(name="bing_images", label="Bing Images"),
    PlatformConfig(name="yandex_images", label="Yandex Images"),
    PlatformConfig(name="ebay", label="eBay"),
    PlatformConfig(name="official", label="Brand official site/search", enabled_by_default=False, speed_tier="deep"),
    PlatformConfig(name="wildberries", label="WB / Wildberries", enabled_by_default=True, speed_tier="deep"),
    PlatformConfig(name="ozon", label="Ozon", enabled_by_default=True, competitor_reference_only=True, speed_tier="deep"),
    PlatformConfig(name="lamoda", label="Lamoda", enabled_by_default=False, speed_tier="deep"),
    PlatformConfig(name="avito", label="Avito", enabled_by_default=False, speed_tier="deep"),
    PlatformConfig(name="stockx", label="StockX", enabled_by_default=False, speed_tier="deep"),
    PlatformConfig(name="goat", label="GOAT", enabled_by_default=False, speed_tier="deep"),
]

OPTIONAL_PLATFORMS = [
    PlatformConfig(name="poizon_visual", label="Poizon Visual", enabled_by_default=True, speed_tier="deep"),
    PlatformConfig(name="kr_poizon", label="KR Poizon", enabled_by_default=True, speed_tier="deep"),
    PlatformConfig(name="yandex_reverse_image", label="Yandex Reverse Image", enabled_by_default=False, speed_tier="deep"),
    PlatformConfig(name="amazon", label="Amazon", enabled_by_default=False),
    PlatformConfig(name="aliexpress", label="AliExpress", enabled_by_default=False),
    PlatformConfig(name="farfetch", label="Farfetch", enabled_by_default=False),
    PlatformConfig(name="megamarket", label="Megamarket", enabled_by_default=False),
    PlatformConfig(name="kazanexpress", label="KazanExpress / Magnit Market", enabled_by_default=False),
]
