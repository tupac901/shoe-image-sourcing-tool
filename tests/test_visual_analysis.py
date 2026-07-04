from pathlib import Path

from PIL import Image, ImageDraw

from shoe_image_sourcing.visual_analysis import analyze_image, profile_similarity_score


def _shoe(path: Path, accent: str = "navy") -> None:
    image = Image.new("RGB", (600, 450), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((90, 240, 500, 350), fill="white", outline=accent, width=12)
    draw.rectangle((160, 190, 440, 290), fill="white", outline=accent, width=10)
    draw.line((180, 235, 380, 255), fill=accent, width=8)
    image.save(path)


def _box(path: Path) -> None:
    image = Image.new("RGB", (600, 450), "gray")
    draw = ImageDraw.Draw(image)
    draw.rectangle((180, 40, 420, 410), fill="slategray", outline="black", width=14)
    draw.rectangle((220, 95, 380, 180), fill="red")
    image.save(path)


def test_visual_profile_similarity_prefers_same_product_shape(tmp_path):
    reference = tmp_path / "reference.jpg"
    similar = tmp_path / "similar.jpg"
    unrelated = tmp_path / "unrelated.jpg"
    _shoe(reference)
    _shoe(similar)
    _box(unrelated)

    assert analyze_image(reference)["foreground_aspect"]
    assert profile_similarity_score(reference, similar) > profile_similarity_score(reference, unrelated)
