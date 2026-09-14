#!/usr/bin/env python3
"""Validate repository JSON schemas and optional manifest instances.

Instance arguments use ``SCHEMA=PATH`` (for example,
``run-manifest=output/run/run-manifest.json``).  The command intentionally
does not search output directories: generated data is local and often contains
user-provided paths.  Callers must opt in to the exact files they want checked.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT / "programs" / "src"))

from asset_extractor.schema import (  # noqa: E402
    SCHEMA_NAMES,
    SchemaContractError,
    check_schema,
    validate_document,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--schema-root",
        type=Path,
        default=SOURCE_ROOT / "development" / "schemas",
        help="directory containing <name>.schema.json files",
    )
    parser.add_argument(
        "--manifest",
        action="append",
        default=[],
        metavar="SCHEMA=PATH",
        help="validate one manifest instance against an allow-listed schema",
    )
    return parser


def _read_manifest(spec: str) -> tuple[str, Path]:
    name, separator, raw_path = spec.partition("=")
    if not separator or not raw_path:
        raise SchemaContractError(f"manifest must use SCHEMA=PATH: {spec}")
    if name not in SCHEMA_NAMES:
        raise SchemaContractError(f"unknown manifest schema: {name}")
    return name, Path(raw_path)


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        for name in SCHEMA_NAMES:
            check_schema(name, arguments.schema_root)
            print(f"schema ok: {name}")
        for spec in arguments.manifest:
            name, path = _read_manifest(spec)
            document = json.loads(path.read_text(encoding="utf-8"))
            errors = validate_document(document, name, arguments.schema_root)
            if errors:
                for error in errors:
                    print(f"{path}: {error}", file=sys.stderr)
                return 2
            print(f"manifest ok: {path} ({name})")
    except (OSError, UnicodeError, json.JSONDecodeError, SchemaContractError) as exc:
        print(f"schema validation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
