from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "programs"))

from run_minimal_restore_test import (  # noqa: E402
    MinimalRestoreError,
    detect_format_bytes,
    run_minimal_restore_test,
)


PNG_FIXTURE = b"\x89PNG\r\n\x1a\nfixture-image"
MP4_FIXTURE = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2fixture-video"


class MinimalRestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_source(self) -> tuple[Path, bytes, bytes]:
        source = self.root / "bluestacks-extracted.obb"
        with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("res/movie/00-invalid.mp4", b"not-a-video")
            archive.writestr("res/movie/01-demo.mp4", MP4_FIXTURE)
            archive.writestr("res/ui/00-invalid.png", b"not-an-image")
            archive.writestr("res/ui/01-demo.png", PNG_FIXTURE)
        return source, MP4_FIXTURE, PNG_FIXTURE

    def make_nxpk_bytes(self, payloads: list[bytes]) -> bytes:
        index_offset = 24
        data_offset = index_offset + 32 * len(payloads)
        entries: list[bytes] = []
        cursor = data_offset
        for index, payload in enumerate(payloads):
            entries.append(
                struct.pack(
                    "<8I",
                    0x1000 + index,
                    0,
                    cursor,
                    len(payload),
                    len(payload),
                    0,
                    0,
                    0,
                )
            )
            cursor += len(payload)
        header = b"NXPK" + struct.pack("<IIIII", len(payloads), 0, 0, 0, index_offset)
        return header + b"".join(entries) + b"".join(payloads)

    def test_magic_detection_is_independent_of_extension(self) -> None:
        self.assertEqual(detect_format_bytes(MP4_FIXTURE)["family"], "video")
        self.assertEqual(detect_format_bytes(PNG_FIXTURE)["format"], "png")
        self.assertEqual(detect_format_bytes(b"not-a-video")["family"], "unknown")

    def test_extract_detect_and_hash_verify_two_members_with_python_only_pipeline(self) -> None:
        source, video, image = self.make_source()
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        output = self.root / "minimal-restore-test"
        manifest = run_minimal_restore_test([source], output, expected_source_sha256=[source_hash])

        self.assertEqual(manifest["status"], "complete")
        self.assertTrue(manifest["policy"]["python_only"])
        self.assertFalse(manifest["policy"]["external_commands"])
        self.assertTrue(manifest["source_unchanged"])
        self.assertEqual(manifest["summary"]["assets_completed"], 2)
        self.assertEqual(manifest["summary"]["hashes_verified"], 2)
        self.assertEqual(manifest["summary"]["formats_verified"], 2)

        assets = {asset["kind"]: asset for asset in manifest["assets"]}
        self.assertEqual(Path(assets["video"]["output"]).read_bytes(), video)
        self.assertEqual(Path(assets["image"]["output"]).read_bytes(), image)
        self.assertTrue(all(asset["hash_match"] for asset in assets.values()))
        self.assertTrue(all(asset["format_match"] for asset in assets.values()))
        self.assertEqual(
            json.loads((output / "minimal-restore-manifest.json").read_text(encoding="utf-8")),
            manifest,
        )
        self.assertFalse(any(output.rglob("*.partial")))

    def test_existing_output_is_refused_without_overwrite(self) -> None:
        source, _, _ = self.make_source()
        output = self.root / "existing-run"
        output.mkdir()
        sentinel = output / "do-not-touch.txt"
        sentinel.write_text("keep", encoding="utf-8")
        with self.assertRaises(MinimalRestoreError):
            run_minimal_restore_test([source], output)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertFalse((output / "minimal-restore-manifest.json").exists())

    def test_image_can_be_restored_from_nested_nxpk_member(self) -> None:
        source = self.root / "nested-image.obb"
        nxpk = self.make_nxpk_bytes([b"not-an-image", PNG_FIXTURE])
        with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("res/movie/demo.mp4", MP4_FIXTURE)
            archive.writestr("tex11.npk", nxpk)
        output = self.root / "nested-image-run"

        manifest = run_minimal_restore_test([source], output)

        self.assertEqual(manifest["status"], "complete")
        assets = {asset["kind"]: asset for asset in manifest["assets"]}
        self.assertFalse(assets["video"]["nested"])
        self.assertTrue(assets["image"]["nested"])
        self.assertEqual(assets["image"]["container_member"], "tex11.npk")
        self.assertEqual(assets["image"]["nested_entry_index"], 1)
        self.assertEqual(Path(assets["image"]["output"]).read_bytes(), PNG_FIXTURE)
        self.assertTrue(assets["image"]["hash_match"])
        self.assertTrue(assets["image"]["format_match"])
        self.assertFalse(any(output.glob(".minimal-restore-nested-*.npk")))


if __name__ == "__main__":
    unittest.main()
