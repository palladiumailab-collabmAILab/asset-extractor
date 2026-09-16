#!/usr/bin/env python3
"""Fail when coverage of critical asset_extractor modules drops below the baseline."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


# Baseline: canonical package-only branch coverage from PR #22 on 2026-09-16.
# Coverage.py's displayed whole-percent value is used intentionally so the gate
# matches the stable precision shown in CI instead of depending on hidden decimals.
MINIMUM_DISPLAY_COVERAGE = {
    "asset_extractor/backends.py": 76,
    "asset_extractor/manifest_validation.py": 72,
    "asset_extractor/orchestrator.py": 67,
    "asset_extractor/pipeline.py": 84,
    "asset_extractor/safety.py": 85,
}


def _normalized(path: str) -> str:
    return path.replace("\\", "/")


def _display_percent(summary: dict[str, Any]) -> int:
    value = summary.get("percent_covered_display")
    if value is None:
        raise ValueError("coverage summary has no percent_covered_display")
    return int(str(value).rstrip("%"))


def check_coverage(document: dict[str, Any]) -> list[str]:
    files = document.get("files")
    if not isinstance(files, dict):
        return ["coverage JSON has no files object"]

    failures: list[str] = []
    for module, minimum in MINIMUM_DISPLAY_COVERAGE.items():
        matches = [
            (path, entry) for path, entry in files.items() if _normalized(path).endswith(module)
        ]
        if len(matches) != 1:
            failures.append(
                f"expected exactly one coverage entry for {module}; found {len(matches)}"
            )
            continue

        path, entry = matches[0]
        if not isinstance(entry, dict) or not isinstance(entry.get("summary"), dict):
            failures.append(f"coverage entry has no summary: {path}")
            continue
        try:
            actual = _display_percent(entry["summary"])
        except (TypeError, ValueError) as exc:
            failures.append(f"invalid coverage summary for {path}: {exc}")
            continue
        if actual < minimum:
            failures.append(f"critical coverage regressed for {module}: {actual}% < {minimum}%")
    return failures


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: check-critical-coverage.py COVERAGE_JSON", file=sys.stderr)
        return 2

    path = Path(args[0])
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read coverage JSON {path}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(document, dict):
        print("coverage JSON root must be an object", file=sys.stderr)
        return 2

    failures = check_coverage(document)
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1

    print("Critical module coverage meets the recorded baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
