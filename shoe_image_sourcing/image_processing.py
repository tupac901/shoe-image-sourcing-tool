from pathlib import Path

import imagehash
from PIL import Image, ImageOps

from . import image_formats  # noqa: F401


TARGET_SIZE = (900, 1200)


def _open_rgb(path: Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def crop_subject_for_matching(image: Image.Image, margin_ratio: float = 0.08) -> Image.Image:
    """Crop large screenshot borders while preserving the product body."""
    rgb = ImageOps.exif_transpose(image).convert("RGB")
    pixels = rgb.load()
    xs: list[int] = []
    ys: list[int] = []
    for y in range(rgb.height):
        for x in range(rgb.width):
            r, g, b = pixels[x, y]
            high = max(r, g, b)
            low = min(r, g, b)
            saturation = high - low
            # Ignore white/very light UI backgrounds and pale gray browser controls.
            if high > 238 and saturation < 24:
                continue
            if high > 218 and saturation < 12:
                continue
            # Keep colored material, dark edges, soles, logos, laces and shadows.
            if saturation >= 16 or high < 185:
                xs.append(x)
                ys.append(y)
    if not xs or not ys:
        return rgb
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    width = right - left + 1
    height = bottom - top + 1
    if width < 80 or height < 80:
        return rgb
    margin = int(max(width, height) * margin_ratio)
    left = max(0, left - margin)
    top = max(0, top - margin)
    right = min(rgb.width, right + margin)
    bottom = min(rgb.height, bottom + margin)
    cropped = rgb.crop((left, top, right + 1, bottom + 1))
    # Avoid over-cropping normal product photos that already fill the frame.
    if cropped.width * cropped.height > rgb.width * rgb.height * 0.92:
        return rgb
    return cropped


def prepare_matching_reference(src: Path, dest: Path) -> Path:
    image = crop_subject_for_matching(_open_rgb(src))
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, "JPEG", quality=94)
    return dest


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
