from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "check-critical-coverage.py"
SPEC = importlib.util.spec_from_file_location("check_critical_coverage", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _coverage_document(overrides: dict[str, int] | None = None) -> dict[str, object]:
    values = dict(MODULE.MINIMUM_DISPLAY_COVERAGE)
    values.update(overrides or {})
    return {
        "files": {
            f"/site-packages/{module}": {
                "summary": {"percent_covered_display": str(percent)}
            }
            for module, percent in values.items()
        }
    }


class CriticalCoverageGateTests(unittest.TestCase):
    def test_baseline_passes(self) -> None:
        self.assertEqual(MODULE.check_coverage(_coverage_document()), [])

    def test_regression_fails(self) -> None:
        document = _coverage_document({"asset_extractor/orchestrator.py": 66})
        failures = MODULE.check_coverage(document)
        self.assertEqual(len(failures), 1)
        self.assertIn("orchestrator.py: 66% < 67%", failures[0])

    def test_missing_module_fails_closed(self) -> None:
        document = _coverage_document()
        del document["files"]["/site-packages/asset_extractor/safety.py"]
        failures = MODULE.check_coverage(document)
        self.assertEqual(len(failures), 1)
        self.assertIn("safety.py", failures[0])


if __name__ == "__main__":
    unittest.main()
