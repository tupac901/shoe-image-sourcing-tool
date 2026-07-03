from __future__ import annotations

from pathlib import Path

import imagehash
from PIL import Image, ImageOps


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def find_reference_image(run_dir: Path) -> Path | None:
    input_dir = run_dir / "input"
    if not input_dir.exists():
        return None
    for path in input_dir.iterdir():
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            return path
    return None


def _open_rgb(path: Path) -> Image.Image:
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def _hashes(path: Path):
    with _open_rgb(path) as image:
        return {
            "phash": imagehash.phash(image),
            "dhash": imagehash.dhash(image),
            "ahash": imagehash.average_hash(image),
            "color": imagehash.colorhash(image, binbits=3),
        }


def is_visually_related(reference_path: Path | None, candidate_path: Path) -> bool:
    if reference_path is None:
        return True
    reference = _hashes(reference_path)
    candidate = _hashes(candidate_path)
    phash_distance = reference["phash"] - candidate["phash"]
    dhash_distance = reference["dhash"] - candidate["dhash"]
    ahash_distance = reference["ahash"] - candidate["ahash"]
    color_distance = reference["color"] - candidate["color"]
    strong_shape_match = phash_distance <= 22 or ahash_distance <= 18
    balanced_match = phash_distance <= 30 and dhash_distance <= 30 and color_distance <= 14
    return strong_shape_match or balanced_match
