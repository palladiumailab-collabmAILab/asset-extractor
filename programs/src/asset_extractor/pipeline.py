from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .common import atomic_write_json, config_hash, file_rows, sha256_file, tool_metadata, utc_now
from .errors import ExtractionError
from .inventory import DEFAULT_LIMITS, detect_kind
from .manifest import validate_manifest
from .nxpk import extract_nxpk
from .safety import (
    assert_output_disjoint,
    resolve_existing_file,
    resolve_output_path,
    validate_zip_infos,
)


def _safe_stem(path: Path, index: int) -> str:
    stem = "".join(character if character.isalnum() or character in "._-" else "_" for character in path.stem)
    return f"{index:03d}-{stem or 'input'}"


def _failure(path: str, error: str, stage: str) -> dict[str, str]:
    return {"path": path, "error": error, "stage": stage}


def _empty_input_row(raw: str | Path, error: str, status: str = "missing") -> dict[str, Any]:
    path = Path(raw).expanduser()
    return {
        "path": str(path.resolve(strict=False)),
        "name": path.name,
        "kind": None,
        "detection": None,
        "status": status,
        "bytes": None,
        "sha256": None,
        "source_sha256_before": None,
        "source_sha256_after": None,
        "source_unchanged": None,
        "error": error,
        "entries": None,
    }


def _prepare_inputs(raw_inputs: list[str]) -> tuple[list[tuple[Path, dict[str, Any]]], list[dict[str, Any]], list[dict[str, str]]]:
    valid: list[tuple[Path, dict[str, Any]]] = []
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for raw in raw_inputs:
        try:
            source = resolve_existing_file(raw)
            kind, evidence = detect_kind(source)
            before = sha256_file(source)
            row = {
                "path": str(source),
                "name": source.name,
                "kind": kind,
                "detection": evidence,
                "status": "ready",
                "bytes": source.stat().st_size,
                "sha256": before,
                "source_sha256_before": before,
                "source_sha256_after": None,
                "source_unchanged": None,
                "error": None,
                "entries": None,
            }
            rows.append(row)
            valid.append((source, row))
        except (OSError, ExtractionError) as exc:
            error = str(exc)
            path = Path(raw).expanduser()
            status = "error" if path.exists() else "missing"
            row = _empty_input_row(raw, error, status)
            rows.append(row)
            failures.append(_failure(row["path"], error, "input"))
    return valid, rows, failures


def _audit_inputs(input_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for row in input_rows:
        before = row["source_sha256_before"]
        if before is None:
            row["source_sha256_after"] = None
            row["source_unchanged"] = None
            continue
        try:
            source_path = Path(row["path"])
            if source_path.is_symlink():
                raise ExtractionError("symbolic-link source appeared during extraction")
            after = sha256_file(source_path)
        except (OSError, ExtractionError, ValueError) as exc:
            row["source_sha256_after"] = None
            row["source_unchanged"] = False
            row["error"] = row["error"] or str(exc)
            failures.append(_failure(row["path"], f"source could not be re-hashed: {exc}", "source-audit"))
            continue
        row["source_sha256_after"] = after
        row["sha256"] = after
        row["source_unchanged"] = after == before
        if after != before:
            failures.append(_failure(row["path"], "source changed during extraction", "source-audit"))
    return failures


def _overall_source_state(input_rows: list[dict[str, Any]]) -> bool | None:
    states = [row["source_unchanged"] for row in input_rows]
    if any(state is False for state in states):
        return False
    if states and all(state is True for state in states):
        return True
    return None


def _normalized_config(profile: str | None, strict: bool | None, limits: dict[str, int | float]) -> dict[str, Any]:
    return {"profile": profile, "strict": strict, "limits": dict(limits)}


def _resume_key(input_rows: list[dict[str, Any]], normalized_config: dict[str, Any]) -> str:
    return config_hash(
        {
            "inputs": [
                {"path": row["path"], "source_sha256": row["source_sha256_before"]}
                for row in input_rows
            ],
            "tool": tool_metadata(),
            "config": normalized_config,
        }
    )


def _claims(source_unchanged: bool | None) -> list[dict[str, str]]:
    if source_unchanged is True:
        return [{"claim": "source files were read without modification", "certainty": "fact"}]
    return [{"claim": "source stability was not established for every requested input", "certainty": "unknown"}]


def _build_manifest(
    *,
    status: str,
    profile: str | None,
    strict: bool | None,
    resume: bool,
    limits: dict[str, int | float],
    input_rows: list[dict[str, Any]],
    output_directory: Path,
    output_files: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    failures: list[dict[str, str]],
    committed: bool,
    resume_key: str | None,
) -> dict[str, Any]:
    normalized = _normalized_config(profile, strict, limits)
    source_unchanged = _overall_source_state(input_rows)
    return {
        "schema_version": 2,
        "operation": "extract",
        "created_at": utc_now(),
        "status": status,
        "tool": tool_metadata(),
        "profile": profile,
        "strict": strict,
        "resume": resume,
        "limits": dict(limits),
        "normalized_config": normalized,
        "config_sha256": config_hash(normalized),
        "resume_key": resume_key,
        "source_unchanged": source_unchanged,
        "inputs": input_rows,
        "outputs": {
            "directory": str(output_directory),
            "files": output_files,
            "count": len(output_files),
            "committed": committed,
        },
        "entries": entries,
        "failures": failures,
        "claims": _claims(source_unchanged),
    }


def _failed_manifest(
    raw_inputs: list[str],
    destination: Path,
    limits: dict[str, int | float],
    failures: list[dict[str, str]],
    input_rows: list[dict[str, Any]],
    profile: str,
    strict: bool,
    resume: bool,
    resume_key: str | None = None,
) -> dict[str, Any]:
    del raw_inputs  # Input paths are already represented by the normalized rows.
    return _build_manifest(
        status="failed",
        profile=profile,
        strict=strict,
        resume=resume,
        limits=limits,
        input_rows=input_rows,
        output_directory=destination / "extracted",
        output_files=[],
        entries=[],
        failures=failures or [_failure(str(destination), "extraction failed", "run")],
        committed=False,
        resume_key=resume_key,
    )


def _extract_zip(source: Path, destination: Path, limits: dict[str, int | float]) -> list[dict[str, Any]]:
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        plan = validate_zip_infos(
            infos,
            int(limits["max_entries"]),
            int(limits["max_member_bytes"]),
            int(limits["max_total_bytes"]),
            float(limits["max_ratio"]),
        )
        rows: list[dict[str, Any]] = []
        for info, name in plan:
            target = destination / Path(name)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            actual_read = 0
            with archive.open(info, "r") as source_stream, target.open("xb") as output_stream:
                while True:
                    chunk = source_stream.read(min(1024 * 1024, info.file_size + 1 - actual_read))
                    if not chunk:
                        break
                    actual_read += len(chunk)
                    if actual_read > info.file_size:
                        raise ExtractionError(f"ZIP member expanded beyond declaration: {name}")
                    output_stream.write(chunk)
                if source_stream.read(1):
                    raise ExtractionError(f"ZIP member read length exceeded declaration: {name}")
            if actual_read != info.file_size:
                raise ExtractionError(f"ZIP member size changed while extracting: {name}")
            rows.append(
                {
                    "path": name,
                    "bytes": actual_read,
                    "sha256": sha256_file(target),
                    "status": "ok",
                    "kind": "zip",
                    "index": None,
                    "payload_id": None,
                    "offset": info.header_offset,
                    "packed_bytes": info.compress_size,
                    "declared_unpacked_bytes": info.file_size,
                    "actual_read_bytes": actual_read,
                    "actual_unpacked_bytes": actual_read,
                    "bounds_checked": True,
                    "size_checked": True,
                    "compression_flag": info.compress_type,
                    "encrypted": bool(info.flag_bits & 0x1),
                }
            )
        return rows


def _manifest_entry(
    source: Path,
    source_root: str,
    source_input_index: int,
    source_sha256: str,
    entry: dict[str, Any],
) -> dict[str, Any]:
    kind = entry.get("kind", "nxpk")
    logical_path = entry["path"] if kind == "zip" else None
    logical_path_status = "archive-member-path" if logical_path else "unavailable-in-nxpk-index"
    asset_type = Path(entry["path"]).suffix.lower().lstrip(".") or "unknown"
    asset_id = config_hash(
        {
            "source_sha256": source_sha256,
            "kind": kind,
            "logical_path": logical_path,
            "index": entry.get("index"),
            "payload_id": entry.get("payload_id"),
            "offset": entry.get("offset"),
            "packed_bytes": entry.get("packed_bytes"),
        }
    )
    return {
        "asset_id": asset_id,
        "source": source.name,
        "source_input_index": source_input_index,
        "source_sha256": source_sha256,
        "path": entry["path"],
        "output_path": f"{source_root}/{entry['path']}",
        "kind": kind,
        "backend": f"builtin-{kind}",
        "logical_path": logical_path,
        "logical_path_status": logical_path_status,
        "asset_type": asset_type,
        "parent_asset_id": None,
        "status": entry["status"],
        "bytes": entry["bytes"],
        "sha256": entry["sha256"],
        "index": entry.get("index"),
        "payload_id": entry.get("payload_id"),
        "offset": entry.get("offset"),
        "packed_bytes": entry.get("packed_bytes"),
        "declared_unpacked_bytes": entry.get("declared_unpacked_bytes"),
        "actual_read_bytes": entry.get("actual_read_bytes"),
        "actual_unpacked_bytes": entry.get("actual_unpacked_bytes", entry["bytes"]),
        "bounds_checked": entry.get("bounds_checked", True),
        "size_checked": entry.get("size_checked", True),
        "compression_flag": entry.get("compression_flag"),
        "encrypted": entry.get("encrypted", False),
    }


def _validate_report_path(report: str | Path | None, destination: Path, sources: list[Path]) -> Path | None:
    if report is None:
        return None
    report_path = resolve_output_path(report)
    if report_path.exists() and report_path.is_dir():
        raise ExtractionError(f"report path is a directory: {report_path}")
    assert_output_disjoint([*sources, destination], report_path)
    return report_path


def _write_failure_report(report_path: Path | None, manifest: dict[str, Any]) -> None:
    if report_path is not None:
        atomic_write_json(report_path, manifest)


def _resume_existing(
    destination: Path,
    input_rows: list[dict[str, Any]],
    failures: list[dict[str, str]],
    profile: str,
    strict: bool,
    limits: dict[str, int | float],
    report_path: Path | None,
) -> dict[str, Any]:
    manifest_path = destination / "run-manifest.json"
    # A best-effort run may intentionally retain an unresolved input. That
    # input is part of the resume key; only a new audit failure is fatal here.
    resume_failures = [failure for failure in failures if failure.get("stage") != "input"]
    try:
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        resume_failures.append(_failure(str(manifest_path), f"cannot read existing manifest: {exc}", "resume"))
        result = _failed_manifest([], destination, limits, resume_failures, input_rows, profile, strict, True)
        _write_failure_report(report_path, result)
        return result

    try:
        tree_errors = validate_manifest(existing, destination / "extracted")
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        tree_errors = [f"manifest validation raised an error: {exc}"]
    normalized = _normalized_config(profile, strict, limits)
    expected_key = _resume_key(input_rows, normalized)
    if tree_errors:
        resume_failures.extend(_failure(str(destination), error, "resume") for error in tree_errors)
    if not isinstance(existing, dict) or existing.get("operation") != "extract":
        resume_failures.append(_failure(str(manifest_path), "existing manifest is not an extract manifest", "resume"))
    else:
        existing_outputs = existing.get("outputs")
        committed = isinstance(existing_outputs, dict) and existing_outputs.get("committed", False)
        if existing.get("status") == "failed" or not committed:
            resume_failures.append(_failure(str(manifest_path), "existing run is not resumable", "resume"))
        if existing.get("tool") != tool_metadata():
            resume_failures.append(_failure(str(manifest_path), "tool metadata does not match", "resume"))
        if existing.get("normalized_config") != normalized:
            resume_failures.append(_failure(str(manifest_path), "normalized configuration does not match", "resume"))
        if existing.get("resume_key") != expected_key:
            resume_failures.append(_failure(str(manifest_path), "source/config/tool resume key does not match", "resume"))
        stored_inputs = existing.get("inputs")
        current_signature = [(row["path"], row["source_sha256_before"]) for row in input_rows]
        stored_signature = (
            [(row.get("path"), row.get("source_sha256_before")) for row in stored_inputs]
            if isinstance(stored_inputs, list)
            else []
        )
        if stored_signature != current_signature:
            resume_failures.append(_failure(str(manifest_path), "input source hash set does not match", "resume"))

    if resume_failures:
        result = _failed_manifest([], destination, limits, resume_failures, input_rows, profile, strict, True)
        _write_failure_report(report_path, result)
        return result
    return existing


def extract_inputs(
    raw_inputs: list[str],
    output: str | Path,
    profile: str = "auto",
    strict: bool = True,
    limits: dict[str, int | float] | None = None,
    resume: bool = False,
    report: str | Path | None = None,
) -> dict[str, Any]:
    if limits and set(limits) - set(DEFAULT_LIMITS):
        unknown = ", ".join(sorted(set(limits) - set(DEFAULT_LIMITS)))
        raise ExtractionError(f"unsupported limit name(s): {unknown}")
    try:
        effective_limits: dict[str, int | float] = {
            "max_entries": int(limits.get("max_entries", DEFAULT_LIMITS["max_entries"]) if limits else DEFAULT_LIMITS["max_entries"]),
            "max_member_bytes": int(limits.get("max_member_bytes", DEFAULT_LIMITS["max_member_bytes"]) if limits else DEFAULT_LIMITS["max_member_bytes"]),
            "max_total_bytes": int(limits.get("max_total_bytes", DEFAULT_LIMITS["max_total_bytes"]) if limits else DEFAULT_LIMITS["max_total_bytes"]),
            "max_ratio": float(limits.get("max_ratio", DEFAULT_LIMITS["max_ratio"]) if limits else DEFAULT_LIMITS["max_ratio"]),
        }
    except (TypeError, ValueError) as exc:
        raise ExtractionError(f"invalid extraction limit: {exc}") from exc
    if profile not in {"auto", "zip", "nxpk"}:
        raise ExtractionError(f"unsupported profile: {profile}")
    for name in ("max_entries", "max_member_bytes", "max_total_bytes"):
        if int(effective_limits[name]) <= 0:
            raise ExtractionError(f"{name} must be positive")
    if float(effective_limits["max_ratio"]) <= 0:
        raise ExtractionError("max_ratio must be positive")

    destination = resolve_output_path(output)
    valid, input_rows, failures = _prepare_inputs(raw_inputs)
    sources = [source for source, _ in valid]
    if sources:
        assert_output_disjoint(sources, destination)
    report_path = _validate_report_path(report, destination, sources)

    if failures and strict:
        failures.extend(_audit_inputs(input_rows))
        result = _failed_manifest(raw_inputs, destination, effective_limits, failures, input_rows, profile, strict, resume)
        _write_failure_report(report_path, result)
        return result
    if not valid:
        failures.extend(_audit_inputs(input_rows))
        result = _failed_manifest(raw_inputs, destination, effective_limits, failures, input_rows, profile, strict, resume)
        _write_failure_report(report_path, result)
        return result

    if destination.exists():
        if resume:
            failures.extend(_audit_inputs(input_rows))
            return _resume_existing(destination, input_rows, failures, profile, strict, effective_limits, report_path)
        failures.append(_failure(str(destination), "output already exists; use a new run directory or --resume", "preflight"))
        failures.extend(_audit_inputs(input_rows))
        result = _failed_manifest(raw_inputs, destination, effective_limits, failures, input_rows, profile, strict, resume)
        _write_failure_report(report_path, result)
        return result

    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.partial-", dir=parent))
    extracted_root = temporary / "extracted"
    extracted_root.mkdir(parents=True, exist_ok=True)
    output_rows: list[dict[str, Any]] = []
    processed = 0
    manifest: dict[str, Any]
    try:
        for index, (source, input_row) in enumerate(valid, start=1):
            source_root = _safe_stem(source, index)
            target = extracted_root / source_root
            try:
                kind = input_row["kind"]
                if profile == "zip" and kind not in {"zip", "apk-zip", "obb-zip"}:
                    raise ExtractionError(f"profile=zip cannot process {source.name}")
                if profile == "nxpk" and kind != "nxpk":
                    raise ExtractionError(f"profile=nxpk cannot process {source.name}")
                if kind in {"zip", "apk-zip", "obb-zip"}:
                    extracted_entries = _extract_zip(source, target, effective_limits)
                elif kind == "nxpk":
                    extracted_entries = extract_nxpk(source, target, effective_limits)["entries"]
                else:
                    raise ExtractionError(f"unsupported input format: {source}")
                source_sha256 = input_row["source_sha256_before"]
                if not isinstance(source_sha256, str):
                    raise ExtractionError(f"source SHA-256 is unavailable for {source.name}")
                output_rows.extend(
                    _manifest_entry(source, source_root, index - 1, source_sha256, entry)
                    for entry in extracted_entries
                )
                input_row["status"] = "ok"
                processed += 1
            except (OSError, ExtractionError, zipfile.BadZipFile) as exc:
                input_row["status"] = "error"
                input_row["error"] = str(exc)
                failures.append(_failure(str(source), str(exc), "extract"))
                shutil.rmtree(target, ignore_errors=True)
                if strict:
                    raise ExtractionError(f"strict extraction failed for {source.name}: {exc}") from exc

        failures.extend(_audit_inputs(input_rows))
        if any(row["source_unchanged"] is False for row in input_rows):
            raise ExtractionError("source hash changed during extraction")
        if not processed:
            raise ExtractionError("no input was extracted successfully")
        output_files = file_rows(extracted_root)
        # Repeat the audit after output hashing so the final provenance check is
        # immediately before manifest creation and the atomic run commit.
        failures.extend(_audit_inputs(input_rows))
        if any(row["source_unchanged"] is False for row in input_rows):
            raise ExtractionError("source hash changed during finalization")
        status = "complete" if not failures else "partial"
        normalized = _normalized_config(profile, strict, effective_limits)
        key = _resume_key(input_rows, normalized)
        manifest = _build_manifest(
            status=status,
            profile=profile,
            strict=strict,
            resume=resume,
            limits=effective_limits,
            input_rows=input_rows,
            output_directory=destination / "extracted",
            output_files=output_files,
            entries=output_rows,
            failures=failures,
            committed=True,
            resume_key=key,
        )
        manifest_errors = validate_manifest(manifest)
        if manifest_errors:
            raise ExtractionError(f"generated manifest is invalid: {'; '.join(manifest_errors)}")
        atomic_write_json(temporary / "run-manifest.json", manifest)
        if destination.exists():
            raise ExtractionError("output appeared before atomic run commit")
        os.replace(temporary, destination)
        temporary = Path()
    except (OSError, ExtractionError, zipfile.BadZipFile) as exc:
        failures.extend(_audit_inputs(input_rows))
        failures.append(_failure(str(exc), str(exc), "run"))
        result = _failed_manifest(raw_inputs, destination, effective_limits, failures, input_rows, profile, strict, resume)
        _write_failure_report(report_path, result)
        return result
    finally:
        if str(temporary) and temporary != Path() and temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)

    _write_failure_report(report_path, manifest)
    return manifest
