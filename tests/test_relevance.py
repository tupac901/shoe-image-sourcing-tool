from PIL import Image, ImageDraw

from shoe_image_sourcing.relevance import is_visually_related


def test_visual_relevance_accepts_same_image(tmp_path):
    reference = tmp_path / "reference.jpg"
    candidate = tmp_path / "candidate.jpg"
    image = Image.new("RGB", (300, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((40, 190, 260, 260), fill="navy")
    draw.rectangle((80, 150, 240, 220), fill="white", outline="navy", width=6)
    image.save(reference)
    image.save(candidate)

    assert is_visually_related(reference, candidate)


def test_visual_relevance_rejects_unrelated_image(tmp_path):
    reference = tmp_path / "reference.jpg"
    candidate = tmp_path / "candidate.jpg"
    shoe_like = Image.new("RGB", (300, 400), "white")
    draw = ImageDraw.Draw(shoe_like)
    draw.ellipse((40, 190, 260, 260), fill="navy")
    draw.rectangle((80, 150, 240, 220), fill="white", outline="navy", width=6)
    shoe_like.save(reference)

    unrelated = Image.new("RGB", (300, 400), "forestgreen")
    draw = ImageDraw.Draw(unrelated)
    for offset in range(0, 300, 30):
        draw.rectangle((offset, 0, offset + 12, 400), fill="orange")
    unrelated.save(candidate)

    assert not is_visually_related(reference, candidate)
