from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import struct
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]

from asset_extractor import pipeline as pipeline_module  # noqa: E402
from asset_extractor.cli import main  # noqa: E402
from asset_extractor.errors import ExtractionError  # noqa: E402
from asset_extractor.inventory import DEFAULT_LIMITS, inspect_zip  # noqa: E402
from asset_extractor.manifest import validate_manifest  # noqa: E402
from asset_extractor.pipeline import extract_inputs  # noqa: E402
from asset_extractor.schema import validate_document  # noqa: E402


JSONSCHEMA_AVAILABLE = importlib.util.find_spec("jsonschema") is not None


class AssetExtractorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_zip(
        self, name: str, entries: list[tuple[str, bytes]], compression: int = zipfile.ZIP_DEFLATED
    ) -> Path:
        path = self.root / name
        with zipfile.ZipFile(path, "w", compression=compression) as archive:
            for member, payload in entries:
                archive.writestr(member, payload)
        return path

    def make_nxpk_entries(
        self,
        name: str,
        records: list[tuple[bytes, int, int | None]],
    ) -> Path:
        path = self.root / name
        index_offset = 20
        data_offset = index_offset + 32 * len(records)
        entries: list[bytes] = []
        payloads: list[bytes] = []
        current_offset = data_offset
        for payload, flags, declared_size in records:
            stored = zlib.compress(payload) if flags & 0xFFFF == 1 else payload
            entries.append(
                struct.pack(
                    "<8I",
                    0x1234 + len(entries),
                    0,
                    current_offset,
                    len(stored),
                    len(payload) if declared_size is None else declared_size,
                    0,
                    0,
                    flags,
                )
            )
            payloads.append(stored)
            current_offset += len(stored)
        header = b"NXPK" + struct.pack("<IIII", len(records), 0, 0, index_offset)
        path.write_bytes(header + b"".join(entries) + b"".join(payloads))
        return path

    def make_nxpk(self, name: str = "sample.npk") -> Path:
        return self.make_nxpk_entries(name, [(b"NXPK fixture payload", 0, None)])

    def make_real_header_nxpk(self, name: str = "real-header.npk") -> Path:
        path = self.root / name
        payload = b"real 24-byte NXPK header"
        index_offset = 24
        data_offset = index_offset + 32
        entry = struct.pack(
            "<8I",
            0x5678,
            0,
            data_offset,
            len(payload),
            len(payload),
            0,
            0,
            0,
        )
        header = b"NXPK" + struct.pack("<IIIII", 1, 0, 0, 0, index_offset)
        path.write_bytes(header + entry + payload)
        return path

    def test_scan_reports_zip_entries_and_hash(self) -> None:
        source = self.make_zip("sample.apk", [("assets/icon.txt", b"hello")])
        report = self.root / "scan.json"
        self.assertEqual(main(["scan", str(source), "--report", str(report)]), 0)
        manifest = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "complete")
        row = manifest["inputs"][0]
        self.assertEqual(row["kind"], "apk-zip")
        self.assertEqual(row["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(row["source_sha256_before"], row["source_sha256_after"])
        self.assertTrue(row["source_unchanged"])
        self.assertEqual(row["entries"][0]["path"], "assets/icon.txt")
        self.assertEqual(validate_manifest(manifest), [])
        if JSONSCHEMA_AVAILABLE:
            self.assertEqual(
                validate_document(
                    manifest,
                    "run-manifest",
                    PROJECT_ROOT / "development" / "schemas",
                ),
                [],
            )

    def test_extract_is_non_destructive_and_manifest_is_hashable(self) -> None:
        source = self.make_zip("sample.obb", [("res/data.bin", b"payload"), ("empty/", b"")])
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        destination = self.root / "run-001"
        manifest = extract_inputs([str(source)], destination)
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(
            (destination / "extracted/001-sample/res/data.bin").read_bytes(), b"payload"
        )
        row = manifest["inputs"][0]
        self.assertEqual(row["source_sha256_before"], before)
        self.assertEqual(row["source_sha256_after"], before)
        self.assertTrue(row["source_unchanged"])
        saved = json.loads((destination / "run-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            saved["outputs"]["files"][0]["sha256"], hashlib.sha256(b"payload").hexdigest()
        )
        entry = saved["entries"][0]
        self.assertRegex(entry["asset_id"], r"^[0-9a-f]{64}$")
        self.assertEqual(entry["source_input_index"], 0)
        self.assertEqual(entry["source_sha256"], before)
        self.assertEqual(entry["backend"], "builtin-zip")
        self.assertEqual(entry["logical_path"], "res/data.bin")
        self.assertEqual(entry["logical_path_status"], "archive-member-path")
        self.assertEqual(entry["asset_type"], "bin")
        self.assertIsNone(entry["parent_asset_id"])
        self.assertEqual(validate_manifest(saved, destination / "extracted"), [])
        if JSONSCHEMA_AVAILABLE:
            self.assertEqual(
                validate_document(
                    saved,
                    "run-manifest",
                    PROJECT_ROOT / "development" / "schemas",
                ),
                [],
            )

    def test_asset_id_is_stable_across_fresh_output_directories(self) -> None:
        source = self.make_zip("stable.zip", [("res/model.mesh", b"same payload")])
        first = extract_inputs([str(source)], self.root / "stable-run-a")
        second = extract_inputs([str(source)], self.root / "stable-run-b")
        self.assertEqual(first["entries"][0]["asset_id"], second["entries"][0]["asset_id"])

    def test_manifest_validation_accepts_legacy_entries_without_provenance_extension(self) -> None:
        source = self.make_zip("legacy.zip", [("res/data.bin", b"payload")])
        manifest = extract_inputs([str(source)], self.root / "legacy-run")
        for key in (
            "asset_id",
            "source_input_index",
            "source_sha256",
            "backend",
            "logical_path",
            "logical_path_status",
            "asset_type",
            "parent_asset_id",
        ):
            manifest["entries"][0].pop(key)
        self.assertEqual(validate_manifest(manifest), [])

    def test_missing_input_fails_before_creating_output_and_records_audit_fields(self) -> None:
        destination = self.root / "run-missing"
        report = self.root / "failed.json"
        manifest = extract_inputs([str(self.root / "missing.apk")], destination, report=report)
        self.assertEqual(manifest["status"], "failed")
        self.assertFalse(destination.exists())
        self.assertIn("does not exist", manifest["failures"][0]["error"])
        row = manifest["inputs"][0]
        self.assertIsNone(row["source_sha256_before"])
        self.assertIsNone(row["source_sha256_after"])
        self.assertIsNone(row["source_unchanged"])
        self.assertEqual(validate_manifest(manifest), [])
        self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["status"], "failed")

    def test_cli_extract_report_persists_failure_manifest(self) -> None:
        source = self.make_zip("cli-bad.zip", [("../escape", b"bad")])
        destination = self.root / "cli-bad-run"
        report = self.root / "cli-bad-report.json"
        self.assertEqual(
            main(["extract", str(source), "--output", str(destination), "--report", str(report)]),
            2,
        )
        saved = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(validate_manifest(saved), [])

    def test_output_inside_input_is_rejected(self) -> None:
        source_dir = self.root / "source-dir"
        source_dir.mkdir()
        source = self.make_zip("source-dir/sample.zip", [("x", b"x")])
        with self.assertRaises(ExtractionError):
            extract_inputs([str(source)], source_dir)

    def test_existing_output_is_never_deleted(self) -> None:
        source = self.make_zip("existing.zip", [("x", b"x")])
        destination = self.root / "existing-run"
        destination.mkdir()
        sentinel = destination / "user-file.txt"
        sentinel.write_text("keep", encoding="utf-8")
        manifest = extract_inputs([str(source)], destination)
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertFalse((destination / "extracted").exists())

    def test_zip_slip_is_rejected_before_writing(self) -> None:
        source = self.make_zip("bad.zip", [("../escape.txt", b"no")])
        destination = self.root / "run-bad"
        manifest = extract_inputs([str(source)], destination)
        self.assertEqual(manifest["status"], "failed")
        self.assertFalse(destination.exists())
        self.assertTrue(any("traversal" in failure["error"] for failure in manifest["failures"]))

    def test_absolute_and_case_collision_are_rejected(self) -> None:
        absolute = self.make_zip("absolute.zip", [("/escape.txt", b"no")])
        self.assertEqual(
            extract_inputs([str(absolute)], self.root / "absolute-run")["status"], "failed"
        )
        collision = self.make_zip("collision.zip", [("A.txt", b"a"), ("a.txt", b"b")])
        self.assertEqual(
            extract_inputs([str(collision)], self.root / "collision-run")["status"], "failed"
        )

    def test_compression_ratio_is_enforced(self) -> None:
        source = self.make_zip("ratio.zip", [("large.txt", b"a" * 10000)])
        limits = dict(DEFAULT_LIMITS, max_ratio=2.0)
        manifest = extract_inputs([str(source)], self.root / "ratio-run", limits=limits)
        self.assertEqual(manifest["status"], "failed")
        self.assertTrue(
            any("compression ratio" in failure["error"] for failure in manifest["failures"])
        )

    def test_limits_are_enforced(self) -> None:
        source = self.make_zip(
            "limited.zip", [("large.bin", b"1234567890")], compression=zipfile.ZIP_STORED
        )
        limits = dict(DEFAULT_LIMITS, max_member_bytes=5)
        manifest = extract_inputs([str(source)], self.root / "limited-run", limits=limits)
        self.assertEqual(manifest["status"], "failed")
        self.assertIn("member limit", manifest["failures"][0]["error"])

    def test_best_effort_commits_partial_output_without_deleting_it(self) -> None:
        source = self.make_zip("good.zip", [("ok.txt", b"ok")])
        destination = self.root / "partial-run"
        manifest = extract_inputs(
            [str(source), str(self.root / "missing.zip")],
            destination,
            strict=False,
        )
        self.assertEqual(manifest["status"], "partial")
        self.assertTrue(destination.exists())
        self.assertTrue((destination / "extracted/001-good/ok.txt").exists())
        self.assertTrue(manifest["failures"])
        self.assertIsNone(manifest["source_unchanged"])
        resumed = extract_inputs(
            [str(source), str(self.root / "missing.zip")],
            destination,
            strict=False,
            resume=True,
        )
        self.assertEqual(resumed["status"], "partial")

    def test_source_change_before_commit_is_failed_and_not_committed(self) -> None:
        source = self.make_zip("changing.zip", [("x.txt", b"x")])
        destination = self.root / "changing-run"
        original = pipeline_module._extract_zip

        def extract_then_change(
            path: Path, target: Path, limits: dict[str, int | float]
        ) -> list[dict[str, object]]:
            rows = original(path, target, limits)
            path.write_bytes(path.read_bytes() + b"changed")
            return rows

        with patch.object(pipeline_module, "_extract_zip", side_effect=extract_then_change):
            manifest = extract_inputs([str(source)], destination)
        self.assertEqual(manifest["status"], "failed")
        self.assertFalse(destination.exists())
        self.assertFalse(manifest["inputs"][0]["source_unchanged"])
        self.assertNotEqual(
            manifest["inputs"][0]["source_sha256_before"],
            manifest["inputs"][0]["source_sha256_after"],
        )

    def test_nxpk_fixture_is_extracted_with_bounds_and_size_evidence(self) -> None:
        source = self.make_nxpk()
        manifest = extract_inputs([str(source)], self.root / "nxpk-run")
        self.assertEqual(manifest["status"], "complete")
        output = self.root / "nxpk-run/extracted/001-sample/0000000_00001234.bin"
        self.assertEqual(output.read_bytes(), b"NXPK fixture payload")
        entry = manifest["entries"][0]
        self.assertTrue(entry["bounds_checked"])
        self.assertTrue(entry["size_checked"])
        self.assertEqual(entry["actual_read_bytes"], entry["packed_bytes"])
        self.assertEqual(entry["actual_unpacked_bytes"], entry["declared_unpacked_bytes"])
        self.assertRegex(entry["asset_id"], r"^[0-9a-f]{64}$")
        self.assertEqual(entry["source_input_index"], 0)
        self.assertEqual(entry["source_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(entry["backend"], "builtin-nxpk")
        self.assertIsNone(entry["logical_path"])
        self.assertEqual(entry["logical_path_status"], "unavailable-in-nxpk-index")
        self.assertEqual(entry["asset_type"], "bin")
        self.assertIsNone(entry["parent_asset_id"])

    def test_real_nxpk_24_byte_header_is_extracted(self) -> None:
        source = self.make_real_header_nxpk()
        manifest = extract_inputs([str(source)], self.root / "real-header-run")
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(
            (
                self.root / "real-header-run/extracted/001-real-header/0000000_00005678.bin"
            ).read_bytes(),
            b"real 24-byte NXPK header",
        )

    def test_nxpk_max_total_bytes_is_enforced(self) -> None:
        source = self.make_nxpk_entries("total.npk", [(b"12345", 0, None), (b"67890", 0, None)])
        limits = dict(DEFAULT_LIMITS, max_total_bytes=9)
        manifest = extract_inputs([str(source)], self.root / "total-run", limits=limits)
        self.assertEqual(manifest["status"], "failed")
        self.assertTrue(
            any("total output limit" in failure["error"] for failure in manifest["failures"])
        )

    def test_nxpk_bounds_and_declared_size_fail_closed(self) -> None:
        source = self.make_nxpk("bounds.npk")
        raw = bytearray(source.read_bytes())
        struct.pack_into("<I", raw, 20 + 8, len(raw) + 1)
        source.write_bytes(raw)
        manifest = extract_inputs([str(source)], self.root / "bounds-run")
        self.assertEqual(manifest["status"], "failed")
        self.assertTrue(any("bounds" in failure["error"] for failure in manifest["failures"]))

        bad_size = self.make_nxpk_entries("size.npk", [(b"x", 0, 2)])
        manifest = extract_inputs([str(bad_size)], self.root / "size-run")
        self.assertEqual(manifest["status"], "failed")
        self.assertTrue(
            any("size mismatch" in failure["error"] for failure in manifest["failures"])
        )

    def test_nxpk_unknown_flag_is_rejected(self) -> None:
        source = self.make_nxpk_entries("flag.npk", [(b"x", 0x20000, None)])
        manifest = extract_inputs([str(source)], self.root / "flag-run")
        self.assertEqual(manifest["status"], "failed")
        self.assertTrue(
            any("unsupported NXPK flag" in failure["error"] for failure in manifest["failures"])
        )

    def test_nxpk_zlib_entry_has_exact_expanded_size(self) -> None:
        source = self.make_nxpk_entries("compressed.npk", [(b"compressed payload", 1, None)])
        manifest = extract_inputs([str(source)], self.root / "compressed-run")
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["entries"][0]["compression_flag"], 1)
        self.assertEqual(
            manifest["entries"][0]["actual_unpacked_bytes"], len(b"compressed payload")
        )

    def test_nxpk_compression_ratio_is_enforced(self) -> None:
        source = self.make_nxpk_entries("compressed-ratio.npk", [(b"a" * 1000, 1, None)])
        manifest = extract_inputs(
            [str(source)],
            self.root / "compressed-ratio-run",
            limits=dict(DEFAULT_LIMITS, max_ratio=2.0),
        )
        self.assertEqual(manifest["status"], "failed")
        self.assertTrue(
            any("compression ratio" in failure["error"] for failure in manifest["failures"])
        )

    def test_resume_revalidates_key_and_output_hashes(self) -> None:
        source = self.make_zip("resume.zip", [("x.txt", b"original")])
        destination = self.root / "resume-run"
        first = extract_inputs([str(source)], destination)
        self.assertEqual(first["status"], "complete")
        resumed = extract_inputs([str(source)], destination, resume=True)
        self.assertEqual(resumed["status"], "complete")
        output = destination / "extracted/001-resume/x.txt"
        output.write_bytes(b"mutated!")
        rejected = extract_inputs([str(source)], destination, resume=True)
        self.assertEqual(rejected["status"], "failed")
        self.assertTrue(any("output files" in failure["error"] for failure in rejected["failures"]))
        self.assertEqual(output.read_bytes(), b"mutated!")

    def test_resume_rejects_missing_output_and_config_mismatch(self) -> None:
        source = self.make_zip("resume2.zip", [("x.txt", b"original")])
        destination = self.root / "resume2-run"
        extract_inputs([str(source)], destination)
        (destination / "extracted/001-resume2/x.txt").unlink()
        rejected = extract_inputs([str(source)], destination, resume=True)
        self.assertEqual(rejected["status"], "failed")
        self.assertTrue(any("output files" in failure["error"] for failure in rejected["failures"]))

        source2 = self.make_zip("resume3.zip", [("x.txt", b"original")])
        destination2 = self.root / "resume3-run"
        extract_inputs([str(source2)], destination2)
        rejected = extract_inputs(
            [str(source2)], destination2, resume=True, limits=dict(DEFAULT_LIMITS, max_entries=10)
        )
        self.assertEqual(rejected["status"], "failed")
        self.assertTrue(
            any(
                "configuration" in failure["error"] or "resume key" in failure["error"]
                for failure in rejected["failures"]
            )
        )

    def test_resume_rejects_symlink_output_when_supported(self) -> None:
        source = self.make_zip("symlink.zip", [("x.txt", b"original")])
        destination = self.root / "symlink-run"
        extract_inputs([str(source)], destination)
        output = destination / "extracted/001-symlink/x.txt"
        backup = self.root / "outside.txt"
        backup.write_text("outside", encoding="utf-8")
        output.unlink()
        try:
            os.symlink(backup, output)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is not available")
        rejected = extract_inputs([str(source)], destination, resume=True)
        self.assertEqual(rejected["status"], "failed")
        self.assertTrue(
            any("symbolic-link" in failure["error"] for failure in rejected["failures"])
        )
        self.assertEqual(backup.read_text(encoding="utf-8"), "outside")

    def test_manifest_validation_command_detects_tampering(self) -> None:
        source = self.make_zip("validate.zip", [("x.txt", b"original")])
        destination = self.root / "validate-run"
        extract_inputs([str(source)], destination)
        manifest_path = destination / "run-manifest.json"
        self.assertEqual(main(["validate-manifest", str(manifest_path)]), 0)
        (destination / "extracted/001-validate/x.txt").write_bytes(b"tampered")
        self.assertEqual(main(["validate-manifest", str(manifest_path)]), 2)

    def test_inventory_rejects_reserved_member(self) -> None:
        source = self.make_zip("reserved.zip", [("CON.txt", b"no")])
        with zipfile.ZipFile(source):
            with self.assertRaises(ExtractionError):
                inspect_zip(source, DEFAULT_LIMITS)

    def test_scan_marks_unknown_input_as_partial(self) -> None:
        source = self.root / "unknown.bin"
        source.write_bytes(b"not an archive")
        report = self.root / "scan.json"
        self.assertEqual(main(["scan", str(source), "--report", str(report)]), 1)
        manifest = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "partial")
        self.assertEqual(manifest["inputs"][0]["status"], "unsupported")
        self.assertEqual(validate_manifest(manifest), [])

    def test_nxpk_truncated_index_fails_closed(self) -> None:
        source = self.root / "truncated.npk"
        source.write_bytes(b"NXPK" + struct.pack("<IIII", 2, 0, 0, 20) + b"x" * 31)
        manifest = extract_inputs([str(source)], self.root / "truncated-run")
        self.assertEqual(manifest["status"], "failed")
        self.assertIn("index exceeds", manifest["failures"][0]["error"])


if __name__ == "__main__":
    unittest.main()
