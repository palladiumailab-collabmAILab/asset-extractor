from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from asset_extractor.inventory import DEFAULT_LIMITS
from asset_extractor.pipeline import extract_inputs


class ExtractorBoundaryTests(unittest.TestCase):
    def test_duplicate_member_names_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "duplicate.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("same.txt", b"a")
                archive.writestr("same.txt", b"b")

            manifest = extract_inputs([str(source)], root / "run")
            self.assertEqual(manifest["status"], "failed")

    def test_entry_count_limit_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "many.zip"
            with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("a.txt", b"a")
                archive.writestr("b.txt", b"b")

            limits = dict(DEFAULT_LIMITS, max_entries=1)
            manifest = extract_inputs([str(source)], root / "run", limits=limits)
            self.assertEqual(manifest["status"], "failed")
            self.assertTrue(
                any("entry" in failure["error"].lower() for failure in manifest["failures"])
            )


if __name__ == "__main__":
    unittest.main()
