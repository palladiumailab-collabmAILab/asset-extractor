from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "programs" / "prepare_textured_pilot.py"
SPEC = importlib.util.spec_from_file_location("prepare_textured_pilot", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PrepareTexturedRuntimeTests(unittest.TestCase):
    def test_publication_status_reflects_each_model_outcome(self) -> None:
        self.assertEqual(MODULE.publication_status([]), "failed")
        self.assertEqual(MODULE.publication_status([{"status": "unresolved"}]), "failed")
        self.assertEqual(
            MODULE.publication_status([{"status": "converted"}, {"status": "unresolved"}]),
            "partial",
        )
        self.assertEqual(
            MODULE.publication_status([{"status": "converted"}, {"status": "converted"}]),
            "complete",
        )

    def test_missing_dependencies_are_reported_deterministically(self) -> None:
        report = {
            "PIL": {"available": True},
            "numpy": {"available": False},
            "texture2ddecoder": {"available": False},
        }
        self.assertEqual(
            MODULE.missing_runtime_dependencies(report),
            ["numpy", "texture2ddecoder"],
        )

    def test_runtime_delegation_reexecutes_the_same_python_script(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary) / "python.exe"
            runtime.write_bytes(b"fixture")
            completed = SimpleNamespace(returncode=7)
            with patch.object(MODULE.subprocess, "run", return_value=completed) as run:
                result = MODULE.maybe_delegate_runtime(
                    ["--run-root", "source", "--runtime-python", str(runtime)],
                    runtime,
                    False,
                )
        self.assertEqual(result, 7)
        command = run.call_args.args[0]
        self.assertEqual(Path(command[0]), runtime.resolve())
        self.assertEqual(Path(command[1]), SCRIPT.resolve())
        self.assertEqual(command[-1], "--_runtime-active")
        self.assertFalse(run.call_args.kwargs["check"])

    def test_active_or_current_runtime_is_not_redelegated(self) -> None:
        with patch.object(MODULE.subprocess, "run") as run:
            self.assertIsNone(
                MODULE.maybe_delegate_runtime([], Path(sys.executable), False)
            )
            self.assertIsNone(
                MODULE.maybe_delegate_runtime([], Path("ignored-python"), True)
            )
        run.assert_not_called()

    def test_upstream_import_preflight_restores_sys_path_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            original_path = list(sys.path)
            with self.assertRaises(ImportError):
                MODULE.load_neoxtractor_modules(Path(temporary))
            self.assertEqual(sys.path, original_path)


if __name__ == "__main__":
    unittest.main()
