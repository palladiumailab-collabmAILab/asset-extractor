from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "programs" / "src"))

from asset_extractor.visual import _ratio_test_matches, compare_images  # noqa: E402


class VisualComparisonTests(unittest.TestCase):
    def test_comparison_is_evidence_and_never_a_binding_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "reference.png"
            candidate = root / "candidate.png"
            Image.new("RGB", (32, 32), (220, 30, 30)).save(reference)
            Image.new("RGB", (32, 32), (220, 30, 30)).save(candidate)
            result = compare_images(reference, candidate)
        self.assertIn(result["status"], {"scored", "unavailable"})
        self.assertEqual(result["reference"], str(reference.resolve()))
        self.assertEqual(result["candidate"], str(candidate.resolve()))
        if result["status"] == "scored":
            self.assertFalse(result["accepted"])
            self.assertEqual(result["confidence"], "low")

    def test_ratio_test_ignores_sparse_knn_rows(self) -> None:
        accepted = SimpleNamespace(distance=10.0)
        rejected = SimpleNamespace(distance=80.0)
        result = _ratio_test_matches(
            [
                [],
                [SimpleNamespace(distance=5.0)],
                [accepted, SimpleNamespace(distance=20.0)],
                [rejected, SimpleNamespace(distance=100.0)],
            ]
        )
        self.assertEqual(result, [accepted])


if __name__ == "__main__":
    unittest.main()
