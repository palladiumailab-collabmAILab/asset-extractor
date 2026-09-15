#!/usr/bin/env python3
"""Run a dedicated NeoX extractor checkout behind a normalized safe wrapper."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


PROGRAMS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROGRAMS_ROOT))
sys.path.insert(0, str(PROGRAMS_ROOT / "src"))

from asset_extractor.common import config_hash, sha256_file, utc_now  # noqa: E402
from asset_extractor.errors import ExtractionError  # noqa: E402
from asset_extractor.pipeline import extract_inputs  # noqa: E402
import run_pilot  # noqa: E402


BACKENDS = ("auto", "builtin", "neoxtractor", "neox-tools")
DEFAULT_NEOX_ROOT = PROGRAMS_ROOT / "vendor" / "resource-onmyoji" / "NeoXtractor-source-v3.2"
DEFAULT_NEOX_CONFIG = DEFAULT_NEOX_ROOT / "configs" / "omy_omrc.json"
DEFAULT_NEOX_PYTHON = DEFAULT_NEOX_ROOT.parent / "neoxtractor-venv" / "Scripts" / "python.exe"
BACKEND_RUNTIME_TIMEOUT_SECONDS = 30 * 60


def _checkout(raw: Path | None, environment_name: str, default: Path) -> Path | None:
    if raw is not None:
        candidate = raw.expanduser().resolve()
    elif os.environ.get(environment_name):
        candidate = Path(os.environ[environment_name]).expanduser().resolve()
    else:
        candidate = default.resolve()
    return candidate if candidate.is_dir() else None


def is_neox_archive(source: Path) -> bool:
    try:
        with source.open("rb") as stream:
            return stream.read(4) in {b"NXPK", b"EXPK"}
    except OSError:
        return False


def select_backend(
    requested: str,
    source: Path,
    game_profile: str,
    neox_root: Path | None,
    neox_tools_root: Path | None,
) -> tuple[str, str]:
    if requested != "auto":
        if requested == "neoxtractor" and neox_root is None:
            raise ExtractionError("NeoXtractor checkout is unavailable")
        if requested == "neox-tools" and neox_tools_root is None:
            raise ExtractionError("neox_tools checkout is unavailable")
        return requested, "explicit"
    if game_profile == "onmyoji" and is_neox_archive(source):
        if neox_root is not None:
            return "neoxtractor", "auto: NeoX archive + game profile + available pinned checkout"
        if neox_tools_root is not None:
            return "neox-tools", "auto: NeoX archive + game profile + available pinned checkout"
        return "builtin", "auto fallback: no dedicated checkout is available"
    return "builtin", "auto fallback: dedicated NeoX identification is insufficient"


def _normalized_external_entries(
    source: Path,
    source_sha256: str,
    backend: str,
    result: dict[str, Any],
    run_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    entries: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for row in result.get("entries", []):
        logical_path = row.get("name") if backend == "neoxtractor" else None
        if logical_path is not None:
            logical_path = str(logical_path).replace("\\", "/")
        output_path = Path(row["output_path"]).resolve() if row.get("output_path") else None
        if output_path is not None:
            try:
                relative_output = output_path.relative_to(run_root).as_posix()
            except ValueError as exc:
                raise ExtractionError(f"backend output escaped run root: {output_path}") from exc
        else:
            relative_output = None
        normalized = {
            "asset_id": config_hash({
                "source_sha256": source_sha256,
                "entry_index": row.get("ordinal"),
                "payload_id": row.get("payload_id"),
                "offset": row.get("offset"),
            }),
            "source": source.name,
            "source_sha256": source_sha256,
            "entry_index": row.get("ordinal"),
            "payload_id": row.get("payload_id"),
            "payload_offset": row.get("offset"),
            "packed_bytes": row.get("packed_bytes"),
            "declared_unpacked_bytes": row.get("declared_unpacked_bytes"),
            "flags": row.get("flags_raw"),
            "backend": backend,
            "backend_revision": result.get("tool_metadata", {}).get("commit"),
            "logical_path": logical_path,
            "logical_path_status": "backend-provided" if logical_path else "unavailable-from-backend",
            "output_path": relative_output,
            "output_sha256": row.get("output_sha256"),
            "bytes": row.get("actual_size"),
            "asset_type": row.get("detected_type") or "unknown",
            "status": "extracted" if row.get("status") == "ok" else "failed",
            "unresolved_reason": row.get("error"),
        }
        entries.append(normalized)
        if normalized["status"] != "extracted":
            failures.append({
                "entry_index": normalized["entry_index"],
                "stage": "dedicated-backend",
                "error": normalized["unresolved_reason"] or "backend extraction failed",
            })
    return entries, failures


def _validate_backend_request(
    source: Path,
    output: Path,
    requested_backend: str,
    game_profile: str,
    neox_root: Path | None,
    neox_config: Path | None,
    neox_tools_root: Path | None,
) -> tuple[Path, Path, str, str, str]:
    """Resolve paths, select a backend, and validate dedicated prerequisites."""

    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        raise ExtractionError(f"source must be an existing regular non-symlink file: {source}")
    if output.exists():
        raise ExtractionError(f"run root already exists: {output}")
    selected, reason = select_backend(requested_backend, source, game_profile, neox_root, neox_tools_root)
    if selected == "neoxtractor":
        if neox_root is None or neox_config is None or not neox_config.is_file():
            raise ExtractionError("NeoXtractor checkout/config is unavailable")
    elif selected == "neox-tools" and neox_tools_root is None:
        raise ExtractionError("neox_tools checkout is unavailable")
    return source, output, selected, reason, sha256_file(source)


def _run_builtin_backend(
    source: Path,
    output: Path,
    reason: str,
) -> dict[str, Any]:
    """Delegate builtin extraction and retain the backend selection claim."""

    manifest = extract_inputs([str(source)], output, profile="auto")
    manifest["claims"].append({"claim": f"backend selection: {reason}", "certainty": "fact"})
    return manifest


def _build_external_manifest(
    *,
    source: Path,
    before: str,
    selected: str,
    reason: str,
    requested_backend: str,
    game_profile: str,
    index: dict[str, Any],
    result: dict[str, Any],
    staging: Path,
) -> dict[str, Any]:
    """Normalize external output and create the dedicated backend manifest."""

    after = sha256_file(source)
    entries, failures = _normalized_external_entries(source, before, selected, result, staging)
    successes = sum(item["status"] == "extracted" for item in entries)
    if before != after:
        failures.append({"entry_index": None, "stage": "source-audit", "error": "source changed during extraction"})
    status = "complete" if entries and successes == len(entries) and not failures else "partial" if successes else "failed"
    return {
        "schema_version": 1,
        "operation": "extract-netease-backend",
        "created_at": utc_now(),
        "status": status,
        "source": {
            "path": str(source),
            "sha256_before": before,
            "sha256_after": after,
            "unchanged": before == after,
        },
        "selection": {
            "requested": requested_backend,
            "selected": selected,
            "reason": reason,
            "game_profile": game_profile,
        },
        "backend": result.get("tool_metadata", {}),
        "configuration_sha256": config_hash({
            "requested_backend": requested_backend,
            "selected_backend": selected,
            "game_profile": game_profile,
            "backend_revision": result.get("tool_metadata", {}).get("commit"),
            "backend_config_sha256": result.get("tool_metadata", {}).get("config_sha256"),
        }),
        "index": {key: value for key, value in index.items() if key != "entries"},
        "entries": entries,
        "summary": {"entries": len(entries), "extracted": successes, "failed": len(entries) - successes},
        "failures": failures,
        "safety": {
            "source_read_only": True,
            "new_run_root": True,
            "output_paths_revalidated": True,
            "backend_exit_or_return_alone_is_not_success": True,
        },
    }


def _run_external_backend(
    *,
    source: Path,
    output: Path,
    before: str,
    selected: str,
    reason: str,
    requested_backend: str,
    game_profile: str,
    neox_root: Path | None,
    neox_config: Path | None,
    neox_tools_root: Path | None,
) -> dict[str, Any]:
    """Execute a dedicated backend in staging and atomically commit its result."""

    index = run_pilot.parse_index(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging: Path | None = Path(tempfile.mkdtemp(prefix=f".{output.name}.partial-", dir=output.parent))
    try:
        if selected == "neoxtractor":
            result = run_pilot.run_neox(source, staging / "raw", index, neox_root, neox_config)
        else:
            result = run_pilot.run_neox_tools(source, staging / "raw", index, neox_tools_root)
        manifest = _build_external_manifest(
            source=source,
            before=before,
            selected=selected,
            reason=reason,
            requested_backend=requested_backend,
            game_profile=game_profile,
            index=index,
            result=result,
            staging=staging,
        )
        run_pilot.write_json(staging / "backend-run-manifest.json", manifest)
        if output.exists():
            raise ExtractionError(f"output appeared before atomic run commit: {output}")
        os.replace(staging, output)
        staging = None
        return manifest
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def run_backend(
    *,
    source: Path,
    output: Path,
    requested_backend: str,
    game_profile: str,
    neox_root: Path | None,
    neox_config: Path | None,
    neox_tools_root: Path | None,
) -> dict[str, Any]:
    source, output, selected, reason, before = _validate_backend_request(
        source,
        output,
        requested_backend,
        game_profile,
        neox_root,
        neox_config,
        neox_tools_root,
    )
    if selected == "builtin":
        return _run_builtin_backend(source, output, reason)
    return _run_external_backend(
        source=source,
        output=output,
        before=before,
        selected=selected,
        reason=reason,
        requested_backend=requested_backend,
        game_profile=game_profile,
        neox_root=neox_root,
        neox_config=neox_config,
        neox_tools_root=neox_tools_root,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--backend", choices=BACKENDS, default="auto")
    parser.add_argument("--game-profile", choices=("generic", "onmyoji"), default="onmyoji", help="use generic to disable game-specific auto selection")
    parser.add_argument("--neoxtractor-root", type=Path)
    parser.add_argument("--neoxtractor-config", type=Path)
    parser.add_argument("--neox-tools-root", type=Path)
    parser.add_argument("--backend-python", type=Path, help="Python runtime containing the selected backend dependencies")
    parser.add_argument("--_backend-runtime-active", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw_argv)
    try:
        neox_root = _checkout(args.neoxtractor_root, "ASSET_EXTRACTOR_NEOXTRACTOR_ROOT", DEFAULT_NEOX_ROOT)
        neox_tools_root = _checkout(args.neox_tools_root, "ASSET_EXTRACTOR_NEOX_TOOLS_ROOT", PROGRAMS_ROOT / "vendor" / "neox_tools")
        selected, _ = select_backend(args.backend, args.source.expanduser().resolve(), args.game_profile, neox_root, neox_tools_root)
        runtime = args.backend_python
        if runtime is None and selected == "neoxtractor" and DEFAULT_NEOX_PYTHON.is_file():
            runtime = DEFAULT_NEOX_PYTHON
        if runtime is not None and selected in {"neoxtractor", "neox-tools"} and not args._backend_runtime_active:
            runtime = runtime.expanduser().resolve()
            if not runtime.is_file():
                raise ExtractionError(f"backend Python runtime is unavailable: {runtime}")
            if runtime != Path(sys.executable).resolve():
                completed = subprocess.run(
                    [str(runtime), str(Path(__file__).resolve()), *raw_argv, "--_backend-runtime-active"],
                    check=False,
                    timeout=BACKEND_RUNTIME_TIMEOUT_SECONDS,
                )
                return completed.returncode
        config = (args.neoxtractor_config or DEFAULT_NEOX_CONFIG).expanduser().resolve()
        manifest = run_backend(
            source=args.source,
            output=args.output,
            requested_backend=args.backend,
            game_profile=args.game_profile,
            neox_root=neox_root,
            neox_config=config,
            neox_tools_root=neox_tools_root,
        )
    except (OSError, ExtractionError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"backend extraction failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": manifest["status"], "output": str(args.output.resolve())}, ensure_ascii=False))
    return {"complete": 0, "partial": 1, "failed": 2}.get(manifest["status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
