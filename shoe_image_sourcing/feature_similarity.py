from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from . import image_formats  # noqa: F401


def _open_gray(path: Path) -> np.ndarray:
    image = ImageOps.exif_transpose(Image.open(path)).convert("L")
    array = np.array(image)
    return cv2.resize(array, (512, 512), interpolation=cv2.INTER_AREA)


def orb_similarity_score(reference_path: Path | None, candidate_path: Path) -> int:
    if reference_path is None:
        return 50
    try:
        reference = _open_gray(reference_path)
        candidate = _open_gray(candidate_path)
        orb = cv2.ORB_create(nfeatures=800)
        ref_points, ref_desc = orb.detectAndCompute(reference, None)
        cand_points, cand_desc = orb.detectAndCompute(candidate, None)
        if ref_desc is None or cand_desc is None or not ref_points or not cand_points:
            return 0
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = matcher.match(ref_desc, cand_desc)
        good_matches = [match for match in matches if match.distance <= 48]
        baseline = max(20, min(len(ref_points), len(cand_points)))
        return max(0, min(100, int((len(good_matches) / baseline) * 100)))
    except Exception:
        return 0
