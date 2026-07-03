from PIL import Image

from shoe_image_sourcing.image_processing import compute_phash, make_thumbnail, process_to_3x4


def test_process_to_3x4_outputs_expected_ratio(tmp_path):
    src = tmp_path / "src.jpg"
    dest = tmp_path / "out.jpg"
    Image.new("RGB", (1000, 500), "white").save(src)
    width, height = process_to_3x4(src, dest)
    assert dest.exists()
    assert (width, height) == (900, 1200)


def test_thumbnail_and_hash(tmp_path):
    src = tmp_path / "src.jpg"
    thumb = tmp_path / "thumb.jpg"
    Image.new("RGB", (800, 800), "white").save(src)
    make_thumbnail(src, thumb)
    assert thumb.exists()
    assert len(compute_phash(src)) >= 16
