from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "programs" / "src"))

from asset_extractor.classification import classify_file  # noqa: E402
from asset_extractor.media_probe import probe_bytes  # noqa: E402


class MediaProbeTests(unittest.TestCase):
    def test_common_formats_have_stable_families(self) -> None:
        cases = {
            b"\x89PNG\r\n\x1a\n": ("png", "image"),
            b"\xabKTX 20\xbb\r\n\x1a\n": ("ktx2", "texture"),
            b"....ftypisom": ("iso-bmff", "video"),
            b"glTFxxxx": ("glb", "3d"),
            b"\x34\x80\xc8\xbb": ("neox-mesh", "3d"),
            b"<MaterialGroup></MaterialGroup>": ("xml-material", "material"),
        }
        for payload, expected in cases.items():
            with self.subTest(expected=expected):
                result = probe_bytes(payload)
                self.assertEqual((result["format"], result["family"]), expected)

    def test_classification_preserves_probe_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "payload.bin"
            path.write_bytes(b"\x89PNG\r\n\x1a\nrest")
            category, evidence, extension = classify_file(path)
        self.assertEqual(category, "image")
        self.assertEqual(extension, "png")
        self.assertEqual(evidence["format"], "png")


if __name__ == "__main__":
    unittest.main()
