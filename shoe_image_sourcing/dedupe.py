from __future__ import annotations

from .models import ImageCandidate


def hamming_distance(hex_a: str, hex_b: str) -> int:
    return bin(int(hex_a, 16) ^ int(hex_b, 16)).count("1")


def group_duplicates(
    candidates: list[ImageCandidate],
    hashes: dict[str, str],
    max_distance: int = 6,
) -> list[ImageCandidate]:
    groups: list[tuple[str, str]] = []
    for candidate in candidates:
        image_hash = hashes.get(candidate.id)
        if not image_hash:
            continue
        assigned = None
        for group_id, group_hash in groups:
            if hamming_distance(image_hash, group_hash) <= max_distance:
                assigned = group_id
                break
        if assigned is None:
            assigned = f"dup-{len(groups) + 1}"
            groups.append((assigned, image_hash))
        candidate.duplicate_group_id = assigned
    return candidates
