from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "programs" / "src"))
MODULE_PATH = PROJECT_ROOT / "programs" / "run_netease_backend.py"
SPEC = importlib.util.spec_from_file_location("run_netease_backend", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

from asset_extractor.schema import validate_document  # noqa: E402


JSONSCHEMA_AVAILABLE = importlib.util.find_spec("jsonschema") is not None


class NetEaseBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "sample.npk"
        self.source.write_bytes(b"NXPK" + b"\0" * 32)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_auto_prefers_neoxtractor_for_profiled_neox_archive(self) -> None:
        selected = MODULE.select_backend("auto", self.source, "onmyoji", self.root, None)
        self.assertEqual(selected[0], "neoxtractor")

    def test_auto_falls_back_when_profile_or_checkout_is_missing(self) -> None:
        self.assertEqual(
            MODULE.select_backend("auto", self.source, "generic", self.root, None)[0], "builtin"
        )
        self.assertEqual(
            MODULE.select_backend("auto", self.source, "onmyoji", None, None)[0], "builtin"
        )

    def test_explicit_missing_backend_fails(self) -> None:
        with self.assertRaises(MODULE.ExtractionError):
            MODULE.select_backend("neoxtractor", self.source, "onmyoji", None, None)

    def test_backend_cli_exposes_runtime_and_both_wrappers(self) -> None:
        args = MODULE.build_parser().parse_args(
            [
                str(self.source),
                "--output",
                str(self.root / "run"),
                "--backend",
                "neox-tools",
                "--backend-python",
                str(self.root / "python.exe"),
            ]
        )
        self.assertEqual(args.backend, "neox-tools")
        self.assertEqual(args.backend_python, self.root / "python.exe")

    def test_external_rows_are_normalized_and_paths_are_checked(self) -> None:
        output = self.root / "run"
        raw = output / "raw"
        raw.mkdir(parents=True)
        payload = raw / "0000000.mesh"
        payload.write_bytes(b"mesh")
        result = {
            "tool_metadata": {"commit": "a" * 40},
            "entries": [
                {
                    "ordinal": 0,
                    "payload_id": 7,
                    "offset": 64,
                    "packed_bytes": 4,
                    "declared_unpacked_bytes": 4,
                    "flags_raw": 0,
                    "name": "model/s2_hairen/s2_hairen.mesh",
                    "output_path": str(payload),
                    "output_sha256": "b" * 64,
                    "actual_size": 4,
                    "detected_type": "mesh",
                    "status": "ok",
                    "error": None,
                }
            ],
        }
        entries, failures = MODULE._normalized_external_entries(
            self.source, "c" * 64, "neoxtractor", result, output
        )
        self.assertFalse(failures)
        self.assertEqual(entries[0]["logical_path"], "model/s2_hairen/s2_hairen.mesh")
        self.assertEqual(entries[0]["output_path"], "raw/0000000.mesh")
        self.assertEqual(entries[0]["backend_revision"], "a" * 40)

    def test_missing_dedicated_config_does_not_poison_output_path(self) -> None:
        output = self.root / "run"
        with self.assertRaises(MODULE.ExtractionError):
            MODULE.run_backend(
                source=self.source,
                output=output,
                requested_backend="neoxtractor",
                game_profile="onmyoji",
                neox_root=self.root,
                neox_config=self.root / "missing-config.json",
                neox_tools_root=None,
            )
        self.assertFalse(output.exists())

    def test_dedicated_backend_commits_staged_run_atomically(self) -> None:
        output = self.root / "run"
        config = self.root / "config.json"
        config.write_text("{}", encoding="utf-8")
        index = {
            "entry_count": 1,
            "index_size": 32,
            "entries": [
                {
                    "ordinal": 0,
                    "payload_id": 7,
                    "offset": 64,
                    "packed_bytes": 4,
                    "declared_unpacked_bytes": 4,
                    "flags_raw": 0,
                }
            ],
        }
        result = {
            "tool_metadata": {"commit": "a" * 40},
            "entries": [
                {
                    "ordinal": 0,
                    "payload_id": 7,
                    "offset": 64,
                    "packed_bytes": 4,
                    "declared_unpacked_bytes": 4,
                    "flags_raw": 0,
                    "name": "model/s2_hairen/s2_hairen.mesh",
                    "output_sha256": "b" * 64,
                    "actual_size": 4,
                    "detected_type": "mesh",
                    "status": "ok",
                    "error": None,
                }
            ],
        }

        def fake_run_neox(source, destination, parsed_index, root, parsed_config):
            destination.mkdir(parents=True)
            payload = destination / "0000000.mesh"
            payload.write_bytes(b"mesh")
            result["entries"][0]["output_path"] = str(payload)
            return result

        with (
            patch.object(MODULE.run_pilot, "parse_index", return_value=index),
            patch.object(MODULE.run_pilot, "run_neox", side_effect=fake_run_neox),
        ):
            manifest = MODULE.run_backend(
                source=self.source,
                output=output,
                requested_backend="neoxtractor",
                game_profile="onmyoji",
                neox_root=self.root,
                neox_config=config,
                neox_tools_root=None,
            )

        self.assertEqual(manifest["status"], "complete")
        self.assertTrue((output / "backend-run-manifest.json").is_file())
        self.assertEqual(manifest["entries"][0]["output_path"], "raw/0000000.mesh")
        if JSONSCHEMA_AVAILABLE:
            self.assertEqual(
                validate_document(
                    json.loads((output / "backend-run-manifest.json").read_text(encoding="utf-8")),
                    "netease-backend-manifest",
                    PROJECT_ROOT / "development" / "schemas",
                ),
                [],
            )
        self.assertFalse(any(self.root.glob(".run.partial-*")))


if __name__ == "__main__":
    unittest.main()
