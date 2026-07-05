from pathlib import Path

import imagehash
from PIL import Image, ImageOps

from . import image_formats  # noqa: F401


TARGET_SIZE = (900, 1200)


def _open_rgb(path: Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def process_to_3x4(src: Path, dest: Path) -> tuple[int, int]:
    image = _open_rgb(src)
    image.thumbnail(TARGET_SIZE, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", TARGET_SIZE, "white")
    x = (TARGET_SIZE[0] - image.width) // 2
    y = (TARGET_SIZE[1] - image.height) // 2
    canvas.paste(image, (x, y))
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, quality=92)
    return canvas.size


def make_thumbnail(src: Path, dest: Path, max_size: tuple[int, int] = (320, 420)) -> tuple[int, int]:
    image = ImageOps.exif_transpose(_open_rgb(src))
    image.thumbnail(max_size, Image.Resampling.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, quality=85)
    return image.size


def compute_phash(path: Path) -> str:
    return str(imagehash.phash(_open_rgb(path)))
