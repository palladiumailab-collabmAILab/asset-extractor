"""Optional, explainable image similarity helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any


MIN_ACCEPTED_SCORE = 0.65
MIN_ACCEPTED_INLIERS = 4


def compare_images(reference: Path, candidate: Path) -> dict[str, Any]:
    """Score a reference/candidate pair using OpenCV when installed.

    This is candidate ranking evidence, not an identity oracle.  A low or
    unavailable score must remain unresolved and must never rewrite material
    bindings or UVs.
    """

    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except ImportError:
        return {
            "status": "unavailable",
            "reason": "opencv-python-headless is not installed",
            "accepted": False,
            "confidence": "unavailable",
            "reference": str(reference),
            "candidate": str(candidate),
        }

    # OpenCV's optional stubs are not consistent across supported versions;
    # keep this adapter's dependency boundary dynamically typed while the
    # public evidence document remains explicitly shaped below.
    cv2_module: Any = cv2
    numpy_module: Any = np
    reference_image = cv2_module.imread(str(reference), cv2_module.IMREAD_COLOR)
    candidate_image = cv2_module.imread(str(candidate), cv2_module.IMREAD_COLOR)
    if reference_image is None or candidate_image is None:
        return {
            "status": "invalid-input",
            "reason": "OpenCV could not decode one image",
            "accepted": False,
            "confidence": "invalid",
            "reference": str(reference),
            "candidate": str(candidate),
        }

    size = (256, 256)
    reference_small = cv2_module.resize(reference_image, size, interpolation=cv2_module.INTER_AREA)
    candidate_small = cv2_module.resize(candidate_image, size, interpolation=cv2_module.INTER_AREA)
    reference_hsv = cv2_module.cvtColor(reference_small, cv2_module.COLOR_BGR2HSV)
    candidate_hsv = cv2_module.cvtColor(candidate_small, cv2_module.COLOR_BGR2HSV)
    reference_hist = cv2_module.normalize(
        cv2_module.calcHist([reference_hsv], [0, 1], None, [32, 32], [0, 180, 0, 256]),
        None,
    )
    candidate_hist = cv2_module.normalize(
        cv2_module.calcHist([candidate_hsv], [0, 1], None, [32, 32], [0, 180, 0, 256]),
        None,
    )
    histogram_correlation = float(
        cv2_module.compareHist(reference_hist, candidate_hist, cv2_module.HISTCMP_CORREL)
    )
    histogram_score = max(0.0, min(1.0, (histogram_correlation + 1.0) / 2.0))

    orb = cv2_module.ORB_create(nfeatures=1000)
    reference_gray = cv2_module.cvtColor(reference_small, cv2_module.COLOR_BGR2GRAY)
    candidate_gray = cv2_module.cvtColor(candidate_small, cv2_module.COLOR_BGR2GRAY)
    reference_keypoints, reference_descriptors = orb.detectAndCompute(reference_gray, None)
    candidate_keypoints, candidate_descriptors = orb.detectAndCompute(candidate_gray, None)
    good_matches = 0
    inlier_matches = 0
    if reference_descriptors is not None and candidate_descriptors is not None:
        matcher = cv2_module.BFMatcher(cv2_module.NORM_HAMMING)
        pairs = matcher.knnMatch(reference_descriptors, candidate_descriptors, k=2)
        good = [first for first, second in pairs if first.distance < 0.75 * second.distance]
        good_matches = len(good)
        if good_matches >= 4:
            source_points = numpy_module.float32([reference_keypoints[item.queryIdx].pt for item in good])
            destination_points = numpy_module.float32([candidate_keypoints[item.trainIdx].pt for item in good])
            _homography, mask = cv2_module.findHomography(
                source_points, destination_points, cv2_module.RANSAC, 5.0
            )
            if mask is not None:
                inlier_matches = int(mask.ravel().sum())
    feature_score = min(1.0, inlier_matches / 20.0) if inlier_matches else min(1.0, good_matches / 40.0)
    score = 0.45 * histogram_score + 0.55 * feature_score
    accepted = score >= MIN_ACCEPTED_SCORE and inlier_matches >= MIN_ACCEPTED_INLIERS
    return {
        "status": "scored",
        "score": round(float(score), 6),
        "histogram_score": round(histogram_score, 6),
        "histogram_correlation": round(histogram_correlation, 6),
        "good_matches": good_matches,
        "inlier_matches": inlier_matches,
        "accepted": accepted,
        "confidence": "high" if accepted else "low",
        "acceptance_policy": {
            "minimum_score": MIN_ACCEPTED_SCORE,
            "minimum_inliers": MIN_ACCEPTED_INLIERS,
        },
        "reference": str(reference.resolve()),
        "candidate": str(candidate.resolve()),
        "method": "HSV histogram + ORB ratio test + RANSAC inliers",
    }
