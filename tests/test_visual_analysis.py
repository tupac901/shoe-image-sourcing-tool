from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from shoe_image_sourcing.crawler import download_and_process_candidates
from shoe_image_sourcing.models import ImageCandidate, ProductFacts
from shoe_image_sourcing.storage import create_run
from shoe_image_sourcing.visual_analysis import analyze_image, profile_similarity_score


def _shoe(path: Path, accent: str = "navy") -> None:
    image = Image.new("RGB", (600, 450), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((90, 240, 500, 350), fill="white", outline=accent, width=12)
    draw.rectangle((160, 190, 440, 290), fill="white", outline=accent, width=10)
    draw.line((180, 235, 380, 255), fill=accent, width=8)
    image.save(path)


def _colored_shoe(path: Path, body: str, accent: str) -> None:
    image = Image.new("RGB", (768, 492), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 210, 680, 310), fill=body, outline=accent, width=8)
    draw.line((240, 220, 520, 300), fill=accent, width=12)
    draw.rectangle((480, 150, 640, 230), fill=body, outline=accent, width=6)
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


def test_visual_profile_similarity_penalizes_foreground_color_mismatch(tmp_path):
    reference = tmp_path / "white-black.jpg"
    same = tmp_path / "white-black-same.jpg"
    pink = tmp_path / "pink-gray.jpg"
    _colored_shoe(reference, body="white", accent="black")
    _colored_shoe(same, body="white", accent="black")
    _colored_shoe(pink, body="pink", accent="gray")

    profile = analyze_image(reference)

    assert "foreground_r" in profile
    assert "pink_ratio" in profile
    assert "dark_ratio" in profile
    assert profile_similarity_score(reference, same) > 90
    assert profile_similarity_score(reference, pink) < 86


@pytest.mark.anyio
async def test_visual_only_match_keeps_high_similarity_candidate(tmp_path):
    manifest, run_dir = create_run(ProductFacts(brand="Nike", model="Air Monarch IV", sku="416355-102"), ["Nike shoe"], ["bing_images"], tmp_path)
    reference = run_dir / "input" / "reference.jpg"
    candidate_path = run_dir / "originals" / "same-shape.jpg"
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    _shoe(reference)
    _shoe(candidate_path)
    candidate = ImageCandidate(
        id="visual-only",
        platform="bing_images",
        source_page_url="https://example.com/gallery",
        image_url="https://example.com/random-file.jpg",
        title="untitled image",
        local_original_path=candidate_path.as_posix(),
    )
    manifest.candidates.append(candidate)

    rejected = await download_and_process_candidates(manifest, run_dir, [candidate], {}, reference)

    assert rejected == 0
    assert candidate.local_processed_path


@pytest.mark.anyio
async def test_visual_only_match_rejects_non_product_title(tmp_path):
    manifest, run_dir = create_run(ProductFacts(brand="Nike", model="Air Monarch IV", sku="416355-102"), ["Nike shoe"], ["bing_images"], tmp_path)
    reference = run_dir / "input" / "reference.jpg"
    candidate_path = run_dir / "originals" / "ace-combat.jpg"
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    _shoe(reference)
    _shoe(candidate_path)
    candidate = ImageCandidate(
        id="ace-combat",
        platform="bing_images",
        source_page_url="https://www.youtube.com/watch?v=gameplay",
        image_url="https://example.com/ace-combat.jpg",
        title="Ace Combat 2 Gameplay PSX YouTube",
        local_original_path=candidate_path.as_posix(),
    )
    manifest.candidates.append(candidate)

    rejected = await download_and_process_candidates(manifest, run_dir, [candidate], {}, reference)

    assert rejected == 1
    assert "visual_mismatch" in candidate.status_labels
    assert candidate.local_processed_path is None
