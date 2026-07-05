from pathlib import Path

from PIL import Image, ImageDraw

from shoe_image_sourcing.feature_similarity import orb_similarity_score


def _structured_shoe(path: Path, accent: str = "black", upper: str = "white") -> None:
    image = Image.new("RGB", (768, 492), "white")
    draw = ImageDraw.Draw(image)
    draw.polygon([(55, 315), (240, 170), (610, 190), (705, 285), (600, 330), (145, 350)], fill=upper, outline=accent)
    draw.line((260, 205, 540, 300), fill=accent, width=16)
    draw.line((280, 245, 560, 205), fill=accent, width=10)
    draw.line((190, 205, 270, 320), fill=accent, width=8)
    for offset in range(0, 6):
        x = 220 + offset * 28
        draw.ellipse((x, 178, x + 12, 190), fill=accent)
        draw.line((x + 6, 190, x + 34, 245), fill=accent, width=5)
    draw.rectangle((135, 332, 630, 365), fill="lightgray", outline=accent)
    image.save(path)


def _different_shoe(path: Path) -> None:
    image = Image.new("RGB", (768, 492), "white")
    draw = ImageDraw.Draw(image)
    draw.polygon([(55, 315), (230, 185), (630, 180), (715, 270), (600, 345), (135, 350)], fill="pink", outline="gray")
    for offset in range(0, 9):
        x = 150 + offset * 50
        draw.line((x, 210, x + 95, 315), fill="gray", width=8)
        draw.line((x, 315, x + 95, 210), fill="gray", width=5)
    draw.rectangle((125, 335, 640, 372), fill="beige", outline="gray")
    image.save(path)


def test_orb_similarity_prefers_same_structure(tmp_path):
    reference = tmp_path / "reference.jpg"
    same = tmp_path / "same.jpg"
    different = tmp_path / "different.jpg"
    _structured_shoe(reference)
    _structured_shoe(same)
    _different_shoe(different)

    assert orb_similarity_score(reference, same) > 60
    assert orb_similarity_score(reference, different) < 20
