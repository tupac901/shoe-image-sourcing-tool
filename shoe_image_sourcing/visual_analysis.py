from __future__ import annotations

from math import sqrt
from pathlib import Path
from statistics import mean

from PIL import Image, ImageFilter, ImageOps, ImageStat

from . import image_formats  # noqa: F401


def _open_rgb(path: Path) -> Image.Image:
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def _background_color(image: Image.Image) -> tuple[int, int, int]:
    width, height = image.size
    points = [
        image.getpixel((0, 0)),
        image.getpixel((width - 1, 0)),
        image.getpixel((0, height - 1)),
        image.getpixel((width - 1, height - 1)),
    ]
    return tuple(int(mean(channel)) for channel in zip(*points))


def _distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _foreground_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    small = image.resize((160, 160), Image.Resampling.LANCZOS)
    background = _background_color(small)
    pixels = small.load()
    xs: list[int] = []
    ys: list[int] = []
    for y in range(small.height):
        for x in range(small.width):
            pixel = pixels[x, y]
            if _distance(pixel, background) > 32 and not (pixel[0] > 245 and pixel[1] > 245 and pixel[2] > 245):
                xs.append(x)
                ys.append(y)
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _foreground_average(image: Image.Image) -> tuple[int, int, int]:
    small = image.resize((160, 160), Image.Resampling.LANCZOS)
    background = _background_color(small)
    pixels = small.load()
    foreground: list[tuple[int, int, int]] = []
    for y in range(small.height):
        for x in range(small.width):
            pixel = pixels[x, y]
            if _distance(pixel, background) > 32 and not (pixel[0] > 245 and pixel[1] > 245 and pixel[2] > 245):
                foreground.append(pixel)
    if not foreground:
        stat = ImageStat.Stat(small)
        return tuple(int(value) for value in stat.mean[:3])
    return tuple(int(mean(channel)) for channel in zip(*foreground))


def _foreground_color_ratios(image: Image.Image) -> dict[str, float]:
    small = image.resize((160, 160), Image.Resampling.LANCZOS)
    background = _background_color(small)
    pixels = small.load()
    foreground: list[tuple[int, int, int]] = []
    for y in range(small.height):
        for x in range(small.width):
            pixel = pixels[x, y]
            if _distance(pixel, background) > 32 and not (pixel[0] > 245 and pixel[1] > 245 and pixel[2] > 245):
                foreground.append(pixel)
    total = max(1, len(foreground))
    pink = sum(1 for r, g, b in foreground if r > 120 and r > g + 12 and r > b + 12) / total
    dark = sum(1 for r, g, b in foreground if max(r, g, b) < 95) / total
    black = sum(1 for r, g, b in foreground if max(r, g, b) < 65) / total
    bluegray = sum(1 for r, g, b in foreground if b >= r + 5 and b >= g - 5 and max(r, g, b) > 80) / total
    neutral = sum(1 for r, g, b in foreground if abs(r - g) < 12 and abs(g - b) < 12) / total
    return {
        "pink_ratio": round(pink, 3),
        "dark_ratio": round(dark, 3),
        "black_ratio": round(black, 3),
        "bluegray_ratio": round(bluegray, 3),
        "neutral_ratio": round(neutral, 3),
    }


def analyze_image(path: Path) -> dict[str, float | int | str]:
    with _open_rgb(path) as image:
        small = image.resize((96, 96), Image.Resampling.LANCZOS)
        stat = ImageStat.Stat(small)
        avg = tuple(int(value) for value in stat.mean[:3])
        foreground_avg = _foreground_average(image)
        color_ratios = _foreground_color_ratios(image)
        bbox = _foreground_bbox(image)
        if bbox:
            left, top, right, bottom = bbox
            foreground_width = max(1, right - left + 1)
            foreground_height = max(1, bottom - top + 1)
            foreground_coverage = (foreground_width * foreground_height) / (160 * 160)
            foreground_aspect = foreground_width / foreground_height
        else:
            foreground_coverage = 1.0
            foreground_aspect = image.width / max(1, image.height)
        edges = small.convert("L").filter(ImageFilter.FIND_EDGES)
        edge_stat = ImageStat.Stat(edges)
        edge_density = min(1.0, edge_stat.mean[0] / 48)
        return {
            "width": image.width,
            "height": image.height,
            "aspect": round(image.width / max(1, image.height), 3),
            "avg_r": avg[0],
            "avg_g": avg[1],
            "avg_b": avg[2],
            "foreground_r": foreground_avg[0],
            "foreground_g": foreground_avg[1],
            "foreground_b": foreground_avg[2],
            **color_ratios,
            "foreground_coverage": round(foreground_coverage, 3),
            "foreground_aspect": round(foreground_aspect, 3),
            "edge_density": round(edge_density, 3),
        }


def profile_similarity_score(reference_path: Path | None, candidate_path: Path) -> int:
    if reference_path is None:
        return 50
    reference = analyze_image(reference_path)
    candidate = analyze_image(candidate_path)
    color_distance = sqrt(
        (float(reference["avg_r"]) - float(candidate["avg_r"])) ** 2
        + (float(reference["avg_g"]) - float(candidate["avg_g"])) ** 2
        + (float(reference["avg_b"]) - float(candidate["avg_b"])) ** 2
    )
    color_score = max(0, 100 - int(color_distance / 2.2))
    foreground_color_distance = sqrt(
        (float(reference["foreground_r"]) - float(candidate["foreground_r"])) ** 2
        + (float(reference["foreground_g"]) - float(candidate["foreground_g"])) ** 2
        + (float(reference["foreground_b"]) - float(candidate["foreground_b"])) ** 2
    )
    foreground_color_score = max(0, 100 - int(foreground_color_distance / 1.7))
    color_structure_delta = (
        abs(float(reference["pink_ratio"]) - float(candidate["pink_ratio"])) * 110
        + abs(float(reference["dark_ratio"]) - float(candidate["dark_ratio"])) * 95
        + abs(float(reference["black_ratio"]) - float(candidate["black_ratio"])) * 80
        + abs(float(reference["bluegray_ratio"]) - float(candidate["bluegray_ratio"])) * 80
        + abs(float(reference["neutral_ratio"]) - float(candidate["neutral_ratio"])) * 55
    )
    color_structure_score = max(0, 100 - int(color_structure_delta))
    aspect_delta = abs(float(reference["foreground_aspect"]) - float(candidate["foreground_aspect"]))
    aspect_score = max(0, 100 - int(aspect_delta * 70))
    coverage_delta = abs(float(reference["foreground_coverage"]) - float(candidate["foreground_coverage"]))
    coverage_score = max(0, 100 - int(coverage_delta * 160))
    edge_delta = abs(float(reference["edge_density"]) - float(candidate["edge_density"]))
    edge_score = max(0, 100 - int(edge_delta * 180))
    score = (
        color_score * 0.14
        + foreground_color_score * 0.24
        + color_structure_score * 0.26
        + aspect_score * 0.16
        + coverage_score * 0.08
        + edge_score * 0.12
    )
    return max(0, min(100, int(score)))
