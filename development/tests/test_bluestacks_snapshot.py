from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "programs"))
MODULE_PATH = PROJECT_ROOT / "programs" / "pull_bluestacks_snapshot.py"
SPEC = importlib.util.spec_from_file_location("pull_bluestacks_snapshot", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

from asset_extractor.schema import validate_document  # noqa: E402


JSONSCHEMA_AVAILABLE = importlib.util.find_spec("jsonschema") is not None


class BlueStacksSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_remote_root_parser_expands_package_and_rejects_unsafe_paths(self) -> None:
        self.assertEqual(
            MODULE.parse_remote_root(
                "data=/sdcard/Android/data/{package}/files", "org.example.game"
            ),
            ("data", "/sdcard/Android/data/org.example.game/files"),
        )
        for raw in (
            "missing-separator",
            "bad name=/sdcard/x",
            "data=relative",
            "data=/sdcard/a/../b",
        ):
            with self.subTest(raw=raw), self.assertRaises(MODULE.AcquisitionError):
                MODULE.parse_remote_root(raw, "org.example.game")
        self.assertEqual(
            MODULE.validate_package("com.netease.onmyoji.na"), "com.netease.onmyoji.na"
        )
        with self.assertRaises(MODULE.AcquisitionError):
            MODULE.validate_package("bad package; command")

    def test_inventory_parser_preserves_relative_paths(self) -> None:
        output = (
            "7|100|/sdcard/game/OptionRes/model2_1.npk\n"
            "9|101|/sdcard/game/OptionRes/sub/tex.npk\n"
        )
        self.assertEqual(
            MODULE.parse_inventory_output("/sdcard/game/OptionRes", output),
            {
                "model2_1.npk": {"size": 7, "mtime_unix": 100},
                "sub/tex.npk": {"size": 9, "mtime_unix": 101},
            },
        )

    def test_inventory_parser_rejects_escape_and_case_collision(self) -> None:
        with self.assertRaises(MODULE.AcquisitionError):
            MODULE.parse_inventory_output("/sdcard/root", "1|1|/sdcard/other/x\n")
        with self.assertRaises(MODULE.AcquisitionError):
            MODULE.parse_inventory_output(
                "/sdcard/root",
                "1|1|/sdcard/root/A.npk\n1|1|/sdcard/root/a.npk\n",
            )

    def test_snapshot_pulls_to_new_directory_and_records_hashes(self) -> None:
        output = self.root / "snapshot"
        metadata = {"model2_1.npk": {"size": 7, "mtime_unix": 100}}

        def fake_pull(_adb: Path, _serial: str, _remote: str, destination: Path) -> None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"payload")

        ready = subprocess.CompletedProcess([], 0, stdout="device\n", stderr="")
        version = subprocess.CompletedProcess(
            [], 0, stdout="Android Debug Bridge version 1.0.41\n", stderr=""
        )
        with (
            patch.object(MODULE, "run_adb", return_value=ready),
            patch.object(
                MODULE, "device_properties", return_value={"ro.product.model": "BlueStacks"}
            ),
            patch.object(MODULE, "remote_inventory", side_effect=[metadata, metadata]),
            patch.object(MODULE, "pull_one", side_effect=fake_pull),
            patch.object(MODULE.subprocess, "run", return_value=version),
        ):
            manifest = MODULE.snapshot(
                adb=Path("C:/tools/adb.exe"),
                serial="127.0.0.1:5555",
                package="org.example.game",
                remote_roots=[("optionres", "/sdcard/game/OptionRes")],
                output=output,
                include_apks=False,
            )

        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["summary"]["files"], 1)
        self.assertEqual(manifest["files"][0]["sha256"], hashlib.sha256(b"payload").hexdigest())
        self.assertTrue(manifest["files"][0]["remote_unchanged"])
        if JSONSCHEMA_AVAILABLE:
            self.assertEqual(
                validate_document(
                    manifest,
                    "bluestacks-snapshot",
                    PROJECT_ROOT / "development" / "schemas",
                ),
                [],
            )
        self.assertEqual((output / "raw/optionres/model2_1.npk").read_bytes(), b"payload")
        saved = json.loads((output / "snapshot-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["files"], manifest["files"])
        with self.assertRaises(MODULE.AcquisitionError):
            MODULE.snapshot(
                adb=Path("C:/tools/adb.exe"),
                serial="x",
                package="x",
                remote_roots=[],
                output=output,
                include_apks=False,
            )

    def test_snapshot_is_incomplete_when_remote_metadata_changes(self) -> None:
        output = self.root / "changed"
        before = {"a.npk": {"size": 1, "mtime_unix": 100}}
        after = {"a.npk": {"size": 1, "mtime_unix": 101}}

        def fake_pull(_adb: Path, _serial: str, _remote: str, destination: Path) -> None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"x")

        ready = subprocess.CompletedProcess([], 0, stdout="device\n", stderr="")
        version = subprocess.CompletedProcess([], 0, stdout="adb version\n", stderr="")
        with (
            patch.object(MODULE, "run_adb", return_value=ready),
            patch.object(MODULE, "device_properties", return_value={}),
            patch.object(MODULE, "remote_inventory", side_effect=[before, after]),
            patch.object(MODULE, "pull_one", side_effect=fake_pull),
            patch.object(MODULE.subprocess, "run", return_value=version),
        ):
            manifest = MODULE.snapshot(
                adb=Path("adb"),
                serial="serial",
                package="package",
                remote_roots=[("raw", "/sdcard/raw")],
                output=output,
                include_apks=False,
            )
        self.assertEqual(manifest["status"], "incomplete")
        self.assertFalse(manifest["files"][0]["remote_unchanged"])

    def test_snapshot_stops_before_pull_when_inventory_exceeds_limit(self) -> None:
        output = self.root / "limited"
        metadata = {"large.npk": {"size": 8, "mtime_unix": 100}}
        ready = subprocess.CompletedProcess([], 0, stdout="device\n", stderr="")
        version = subprocess.CompletedProcess([], 0, stdout="adb version\n", stderr="")
        with (
            patch.object(MODULE, "run_adb", return_value=ready),
            patch.object(MODULE, "device_properties", return_value={}),
            patch.object(MODULE, "remote_inventory", return_value=metadata),
            patch.object(MODULE, "pull_one") as pull,
            patch.object(MODULE.subprocess, "run", return_value=version),
        ):
            manifest = MODULE.snapshot(
                adb=Path("adb"),
                serial="serial",
                package="package.name",
                remote_roots=[("raw", "/sdcard/raw")],
                output=output,
                include_apks=False,
                max_file_bytes=7,
            )
        self.assertEqual(manifest["status"], "incomplete")
        self.assertEqual(manifest["summary"]["files"], 0)
        pull.assert_not_called()


if __name__ == "__main__":
    unittest.main()
