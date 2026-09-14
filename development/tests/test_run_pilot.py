from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "programs" / "run_pilot.py"
SPEC = importlib.util.spec_from_file_location("run_pilot", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _index() -> dict[str, object]:
    return {
        "entry_count": 1,
        "index_size": 32,
        "entries": [
            {
                "ordinal": 0,
                "payload_id": 1,
                "offset": 24,
                "packed_bytes": 4,
                "declared_unpacked_bytes": 4,
                "flags_raw": 0,
                "compression_flag": 0,
                "encryption_flag": 0,
            }
        ],
    }


class RunPilotBoundaryTests(unittest.TestCase):
    def test_neox_failure_restores_exact_import_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.npk"
            source.write_bytes(b"source")
            config = root / "config.json"
            config.write_text("{}", encoding="utf-8")
            original_path = list(MODULE.sys.path)
            original_cwd = Path.cwd()
            with patch.object(MODULE, "tool_version", return_value={}), patch.object(
                MODULE.importlib, "import_module", side_effect=RuntimeError("upstream import failed")
            ):
                result = MODULE.run_neox(source, root / "neox", _index(), root, config)
            self.assertEqual(MODULE.sys.path, original_path)
            self.assertEqual(Path.cwd(), original_cwd)
            self.assertEqual(result["status_counts"], {"failed": 1})

    def test_neox_tools_failure_restores_cwd_and_import_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.npk"
            source.write_bytes(b"source")
            original_path = list(MODULE.sys.path)
            original_cwd = Path.cwd()

            def fail_unpack(_path: str) -> None:
                raise RuntimeError("upstream unpack failed")

            upstream = SimpleNamespace(unpack=fail_unpack)
            with patch.object(MODULE, "tool_version", return_value={}), patch.object(
                MODULE.importlib, "import_module", return_value=upstream
            ):
                result = MODULE.run_neox_tools(source, root / "neox-tools", _index(), root)
            self.assertEqual(MODULE.sys.path, original_path)
            self.assertEqual(Path.cwd(), original_cwd)
            self.assertEqual(result["status_counts"], {"failed": 1})

    def test_json_write_removes_partial_file_after_serialization_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.json"
            with self.assertRaises(TypeError):
                MODULE.write_json(path, {"unsupported": object()})
            self.assertFalse(list(Path(temporary).glob(".report.json.*.tmp")))


if __name__ == "__main__":
    unittest.main()
