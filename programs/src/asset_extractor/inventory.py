from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

from .common import config_hash, sha256_file, tool_metadata, utc_now
from .errors import ExtractionError
from .safety import validate_zip_infos


DEFAULT_LIMITS: dict[str, int | float] = {
    "max_entries": 200_000,
    "max_member_bytes": 4 * 1024 * 1024 * 1024,
    "max_total_bytes": 32 * 1024 * 1024 * 1024,
    "max_ratio": 10_000.0,
}


def detect_kind(path: Path) -> tuple[str, str]:
    with path.open("rb") as handle:
        header = handle.read(16)
    if header.startswith(b"NXPK"):
        return "nxpk", "magic:NXPK"
    if zipfile.is_zipfile(path):
        suffix = path.suffix.lower()
        if suffix == ".apk":
            return "apk-zip", "zip-central-directory+suffix:.apk"
        if suffix == ".obb":
            return "obb-zip", "zip-central-directory+suffix:.obb"
        return "zip", "zip-central-directory"
    if header.startswith(b"PK\x03\x04"):
        return "zip", "magic:PK"
    return "unknown", "no-known-magic"


def inspect_zip(path: Path, limits: dict[str, int | float]) -> list[dict[str, Any]]:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            plan = validate_zip_infos(
                infos,
                int(limits["max_entries"]),
                int(limits["max_member_bytes"]),
                int(limits["max_total_bytes"]),
                float(limits["max_ratio"]),
            )
            return [
                {
                    "path": name,
                    "bytes": info.file_size,
                    "compressed_bytes": info.compress_size,
                    "is_directory": info.is_dir(),
                    "crc32": f"{info.CRC:08x}",
                }
                for info, name in plan
            ]
    except zipfile.BadZipFile as exc:
        raise ExtractionError(f"invalid ZIP archive: {path}") from exc


def scan_file(path: Path, limits: dict[str, int | float]) -> dict[str, Any]:
    before = sha256_file(path)
    row: dict[str, Any] = {
        "path": str(path),
        "name": path.name,
        "kind": None,
        "detection": None,
        "bytes": path.stat().st_size,
        "sha256": before,
        "source_sha256_before": before,
        "source_sha256_after": None,
        "source_unchanged": None,
        "status": "ready",
        "error": None,
        "entries": None,
    }
    try:
        kind, evidence = detect_kind(path)
        row["kind"] = kind
        row["detection"] = evidence
        if kind in {"apk-zip", "obb-zip", "zip"}:
            row["entries"] = inspect_zip(path, limits)
            row["status"] = "ok"
        elif kind == "unknown":
            row["status"] = "unsupported"
        else:
            row["status"] = "ok"
    except (OSError, ExtractionError) as exc:
        row["status"] = "error"
        row["error"] = str(exc)
    try:
        after = sha256_file(path)
    except OSError as exc:
        row["source_sha256_after"] = None
        row["source_unchanged"] = False
        row["error"] = row["error"] or str(exc)
        row["status"] = "error"
    else:
        row["source_sha256_after"] = after
        row["source_unchanged"] = after == before
        row["sha256"] = after
        if after != before:
            row["status"] = "error"
            row["error"] = row["error"] or "source changed during scan"
    return row


def build_scan_manifest(raw_inputs: list[str], limits: dict[str, int | float]) -> dict[str, Any]:
    inputs: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for raw in raw_inputs:
        path = Path(raw).expanduser()
        if not path.exists():
            resolved = path.resolve(strict=False)
            inputs.append(
                {
                    "path": str(resolved),
                    "name": path.name,
                    "kind": None,
                    "detection": None,
                    "status": "missing",
                    "bytes": None,
                    "sha256": None,
                    "source_sha256_before": None,
                    "source_sha256_after": None,
                    "source_unchanged": None,
                    "error": "input does not exist",
                    "entries": None,
                }
            )
            failures.append({"path": str(resolved), "error": "input does not exist", "stage": "input"})
            continue
        paths = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
        for item in paths:
            try:
                row = scan_file(item.resolve(), limits)
                inputs.append(row)
                if row["status"] == "error":
                    failures.append({"path": row["path"], "error": row["error"] or "scan failed", "stage": "scan"})
                elif row["source_unchanged"] is False:
                    failures.append({"path": row["path"], "error": "source changed during scan", "stage": "source-audit"})
            except (OSError, ExtractionError) as exc:
                failures.append({"path": str(item), "error": str(exc), "stage": "scan"})
    unsupported = [row for row in inputs if row.get("status") != "ok"]
    source_states = [row["source_unchanged"] for row in inputs]
    source_unchanged = False if any(state is False for state in source_states) else True if source_states and all(state is True for state in source_states) else None
    normalized_config = {"profile": None, "strict": None, "limits": dict(limits)}
    return {
        "schema_version": 2,
        "operation": "scan",
        "created_at": utc_now(),
        "status": "failed" if failures else ("partial" if unsupported else "complete"),
        "tool": tool_metadata(),
        "profile": None,
        "strict": None,
        "resume": False,
        "limits": limits,
        "normalized_config": normalized_config,
        "config_sha256": config_hash(normalized_config),
        "resume_key": None,
        "source_unchanged": source_unchanged,
        "inputs": inputs,
        "outputs": {"directory": None, "files": [], "count": 0, "committed": False},
        "entries": [],
        "failures": failures,
        "claims": (
            [{"claim": "source files were read without modification", "certainty": "fact"}]
            if source_unchanged is True
            else [{"claim": "source stability was not established for every requested input", "certainty": "unknown"}]
        ),
    }
