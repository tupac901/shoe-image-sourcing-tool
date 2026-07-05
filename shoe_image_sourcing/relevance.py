from __future__ import annotations

from pathlib import Path

import imagehash
from PIL import Image, ImageOps

from . import image_formats  # noqa: F401


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif"}


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
    score = visual_similarity_score(reference_path, candidate_path)
    return score >= 45


def visual_similarity_score(reference_path: Path | None, candidate_path: Path) -> int:
    if reference_path is None:
        return 50
    reference = _hashes(reference_path)
    candidate = _hashes(candidate_path)
    phash_distance = reference["phash"] - candidate["phash"]
    dhash_distance = reference["dhash"] - candidate["dhash"]
    ahash_distance = reference["ahash"] - candidate["ahash"]
    color_distance = reference["color"] - candidate["color"]
    score = 0
    if phash_distance <= 22:
        score += 35
    elif phash_distance <= 30:
        score += 20
    if ahash_distance <= 18:
        score += 30
    elif ahash_distance <= 28:
        score += 15
    if dhash_distance <= 26:
        score += 20
    elif dhash_distance <= 34:
        score += 8
    if color_distance <= 12:
        score += 20
    elif color_distance <= 18:
        score += 8
    return min(score, 100)
