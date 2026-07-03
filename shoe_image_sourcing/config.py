from pathlib import Path

from .models import PlatformConfig


OUTPUT_ROOT = Path("outputs/shoe_image_sourcing/runs")
MAX_UPLOAD_MB = 8
MAX_IMAGES_PER_RUN = 80
SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}

DEFAULT_PLATFORMS = [
    PlatformConfig(name="wildberries", label="WB / Wildberries"),
    PlatformConfig(name="yandex_images", label="Yandex Images"),
    PlatformConfig(name="ozon", label="Ozon", competitor_reference_only=True),
    PlatformConfig(name="ebay", label="eBay"),
    PlatformConfig(name="official", label="Brand official site/search"),
    PlatformConfig(name="lamoda", label="Lamoda"),
    PlatformConfig(name="avito", label="Avito"),
    PlatformConfig(name="stockx", label="StockX"),
    PlatformConfig(name="goat", label="GOAT"),
]

OPTIONAL_PLATFORMS = [
    PlatformConfig(name="amazon", label="Amazon", enabled_by_default=False),
    PlatformConfig(name="aliexpress", label="AliExpress", enabled_by_default=False),
    PlatformConfig(name="farfetch", label="Farfetch", enabled_by_default=False),
    PlatformConfig(name="megamarket", label="Megamarket", enabled_by_default=False),
    PlatformConfig(name="kazanexpress", label="KazanExpress / Magnit Market", enabled_by_default=False),
]
