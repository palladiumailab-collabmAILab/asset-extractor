from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .common import atomic_write_json
from .errors import ExtractionError
from .inventory import DEFAULT_LIMITS, build_scan_manifest
from .manifest import validate_manifest
from .matcher import write_match_manifest
from .pipeline import extract_inputs
from .safety import assert_output_disjoint, resolve_output_path


def _limits(arguments: argparse.Namespace) -> dict[str, int | float]:
    limits = dict(DEFAULT_LIMITS)
    for name in ("max_entries", "max_member_bytes", "max_total_bytes", "max_ratio"):
        value = getattr(arguments, name, None)
        if value is not None:
            limits[name] = value
    return limits


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asset-extractor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="inventory inputs without extracting them")
    scan.add_argument("inputs", nargs="+", help="files or directories to inspect")
    scan.add_argument("--report", type=Path, help="write the JSON report atomically")
    _add_limits(scan)

    extract = subparsers.add_parser("extract", help="safely extract ZIP/APK/OBB/NXPK inputs")
    extract.add_argument("inputs", nargs="+", help="input files")
    extract.add_argument("--output", required=True, type=Path, help="new run directory")
    extract.add_argument("--profile", choices=("auto", "zip", "nxpk"), default="auto")
    extract.add_argument("--best-effort", action="store_true", help="record missing inputs and continue where safe")
    extract.add_argument("--resume", action="store_true", help="reuse only a manifest and output tree whose hashes and key match")
    extract.add_argument("--report", type=Path, help="write a success or failure JSON report atomically")
    _add_limits(extract)

    validate = subparsers.add_parser("validate-manifest", help="validate one or more manifests and their output hashes")
    validate.add_argument("manifests", nargs="+", type=Path)

    match = subparsers.add_parser("match-assets", help="match logical asset names to an external game dictionary")
    match.add_argument("--dictionary", required=True, type=Path, help="CSV or JSON entity dictionary")
    match.add_argument("--assets", required=True, type=Path, help="JSON manifest containing assets[] or entries[]")
    match.add_argument("--output", required=True, type=Path, help="new match manifest path")
    return parser


def _add_limits(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-entries", dest="max_entries", type=int)
    parser.add_argument("--max-member-bytes", dest="max_member_bytes", type=int)
    parser.add_argument("--max-total-bytes", dest="max_total_bytes", type=int)
    parser.add_argument("--max-ratio", dest="max_ratio", type=float)


def _status_exit_code(status: str) -> int:
    return {"complete": 0, "partial": 1, "failed": 2}.get(status, 2)


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "validate-manifest":
            all_valid = True
            for manifest_path in arguments.manifests:
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    output_root = None
                    outputs = manifest.get("outputs") if isinstance(manifest, dict) else None
                    if isinstance(outputs, dict) and outputs.get("committed"):
                        output_root = outputs.get("directory")
                    errors = validate_manifest(manifest, output_root)
                except (AttributeError, KeyError, OSError, TypeError, ValueError) as exc:
                    errors = [str(exc)]
                if errors:
                    all_valid = False
                    print(json.dumps({"path": str(manifest_path), "valid": False, "errors": errors}, ensure_ascii=False, indent=2))
                else:
                    print(json.dumps({"path": str(manifest_path), "valid": True}, ensure_ascii=False, indent=2))
            return 0 if all_valid else 2
        if arguments.command == "match-assets":
            manifest = write_match_manifest(arguments.dictionary, arguments.assets, arguments.output)
            print(json.dumps(manifest["summary"], ensure_ascii=False, indent=2))
            return 0
        if arguments.command == "scan":
            if arguments.report:
                existing_inputs = [Path(item).expanduser().resolve(strict=False) for item in arguments.inputs if Path(item).expanduser().exists()]
                if existing_inputs:
                    assert_output_disjoint(existing_inputs, resolve_output_path(arguments.report))
            manifest = build_scan_manifest(arguments.inputs, _limits(arguments))
            if arguments.report:
                atomic_write_json(resolve_output_path(arguments.report), manifest)
            else:
                print(json.dumps(manifest, ensure_ascii=False, indent=2))
            return _status_exit_code(manifest["status"])
        manifest = extract_inputs(
            arguments.inputs,
            arguments.output,
            profile=arguments.profile,
            strict=not arguments.best_effort,
            limits=_limits(arguments),
            resume=arguments.resume,
            report=arguments.report,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return _status_exit_code(manifest["status"])
    except (OSError, ExtractionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
