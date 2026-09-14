from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .common import config_hash, file_rows
from .errors import ExtractionError


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TOP_LEVEL_KEYS = {
    "schema_version",
    "operation",
    "created_at",
    "status",
    "tool",
    "profile",
    "strict",
    "resume",
    "limits",
    "normalized_config",
    "config_sha256",
    "resume_key",
    "source_unchanged",
    "inputs",
    "outputs",
    "entries",
    "failures",
    "claims",
}
_INPUT_KEYS = {
    "path",
    "name",
    "kind",
    "detection",
    "status",
    "bytes",
    "sha256",
    "source_sha256_before",
    "source_sha256_after",
    "source_unchanged",
    "error",
    "entries",
}
_OUTPUT_KEYS = {"directory", "files", "count", "committed"}
_FILE_KEYS = {"path", "bytes", "sha256"}
_ENTRY_KEYS = {
    "source",
    "path",
    "output_path",
    "kind",
    "status",
    "bytes",
    "sha256",
    "index",
    "payload_id",
    "offset",
    "packed_bytes",
    "declared_unpacked_bytes",
    "actual_read_bytes",
    "actual_unpacked_bytes",
    "bounds_checked",
    "size_checked",
    "compression_flag",
    "encrypted",
}
_ENTRY_OPTIONAL_KEYS = {
    "asset_id",
    "source_input_index",
    "source_sha256",
    "backend",
    "logical_path",
    "logical_path_status",
    "asset_type",
    "parent_asset_id",
}
_FAILURE_KEYS = {"path", "error", "stage"}
_CLAIM_KEYS = {"claim", "certainty"}
_SCAN_ENTRY_KEYS = {"path", "bytes", "compressed_bytes", "is_directory", "crc32"}


def _check_keys(value: Any, expected: set[str], label: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return False
    unexpected = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if unexpected:
        errors.append(f"{label} has unexpected keys: {', '.join(unexpected)}")
    if missing:
        errors.append(f"{label} is missing keys: {', '.join(missing)}")
    return not unexpected and not missing


def _check_keys_with_optional(
    value: Any,
    required: set[str],
    optional: set[str],
    label: str,
    errors: list[str],
) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return False
    unexpected = sorted(set(value) - required - optional)
    missing = sorted(required - set(value))
    if unexpected:
        errors.append(f"{label} has unexpected keys: {', '.join(unexpected)}")
    if missing:
        errors.append(f"{label} is missing keys: {', '.join(missing)}")
    return not unexpected and not missing


def _check_sha(value: Any, label: str, errors: list[str], nullable: bool = True) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        errors.append(f"{label} must be a lowercase SHA-256 hex string")


def _check_nonnegative_int(value: Any, label: str, errors: list[str], nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        errors.append(f"{label} must be a non-negative integer")


def _overall_source_state(inputs: list[dict[str, Any]]) -> bool | None:
    states = [item.get("source_unchanged") if isinstance(item, dict) else None for item in inputs]
    if not states or any(state is False for state in states):
        return False if any(state is False for state in states) else None
    if all(state is True for state in states):
        return True
    return None


def _validate_output_tree(manifest: dict[str, Any], root: Path, errors: list[str]) -> None:
    if manifest["outputs"].get("directory") != str(root):
        errors.append("manifest output directory does not match the requested output root")
    if not root.exists():
        errors.append(f"output directory is missing: {root}")
        return
    if not root.is_dir():
        errors.append(f"output root is not a directory: {root}")
        return
    try:
        actual = file_rows(root)
    except (OSError, ExtractionError) as exc:
        errors.append(f"cannot inspect output tree: {exc}")
        return
    expected = manifest["outputs"]["files"]
    if actual != expected:
        errors.append("output files do not match manifest paths, sizes, or hashes")


def validate_manifest(manifest: Any, output_root: str | Path | None = None) -> list[str]:
    """Validate the repository's strict run-manifest contract.

    This deliberately uses only the standard library so a report can be checked
    in the same environment that produced it. An optional output root enables
    the second half of validation: checking every recorded output hash against
    the files on disk.
    """

    errors: list[str] = []
    if not _check_keys(manifest, _TOP_LEVEL_KEYS, "manifest", errors):
        return errors
    if manifest["schema_version"] != 2:
        errors.append("schema_version must be 2")
    if manifest["operation"] not in {"scan", "extract"}:
        errors.append("operation must be scan or extract")
    if not isinstance(manifest["created_at"], str) or not manifest["created_at"]:
        errors.append("created_at must be a non-empty string")
    if manifest["status"] not in {"complete", "partial", "failed"}:
        errors.append("status must be complete, partial, or failed")

    tool = manifest["tool"]
    if _check_keys(tool, {"name", "version"}, "tool", errors):
        if not all(isinstance(tool[key], str) and tool[key] for key in ("name", "version")):
            errors.append("tool name and version must be non-empty strings")

    if manifest["profile"] is not None and not isinstance(manifest["profile"], str):
        errors.append("profile must be a string or null")
    if manifest["strict"] is not None and not isinstance(manifest["strict"], bool):
        errors.append("strict must be a boolean or null")
    if not isinstance(manifest["resume"], bool):
        errors.append("resume must be a boolean")

    limits = manifest["limits"]
    if _check_keys(limits, {"max_entries", "max_member_bytes", "max_total_bytes", "max_ratio"}, "limits", errors):
        _check_nonnegative_int(limits["max_entries"], "limits.max_entries", errors)
        _check_nonnegative_int(limits["max_member_bytes"], "limits.max_member_bytes", errors)
        _check_nonnegative_int(limits["max_total_bytes"], "limits.max_total_bytes", errors)
        if not isinstance(limits["max_ratio"], (int, float)) or isinstance(limits["max_ratio"], bool) or limits["max_ratio"] <= 0:
            errors.append("limits.max_ratio must be a positive number")

    normalized = manifest["normalized_config"]
    if _check_keys(normalized, {"profile", "strict", "limits"}, "normalized_config", errors):
        if normalized["profile"] != manifest["profile"] or normalized["strict"] != manifest["strict"] or normalized["limits"] != limits:
            errors.append("normalized_config does not match manifest configuration")
        if config_hash(normalized) != manifest["config_sha256"]:
            errors.append("config_sha256 does not match normalized_config")
    _check_sha(manifest["config_sha256"], "config_sha256", errors, nullable=False)
    _check_sha(manifest["resume_key"], "resume_key", errors)

    if not isinstance(manifest["inputs"], list):
        errors.append("inputs must be an array")
        inputs: list[dict[str, Any]] = []
    else:
        inputs = manifest["inputs"]
    for index, item in enumerate(inputs):
        label = f"inputs[{index}]"
        if not _check_keys(item, _INPUT_KEYS, label, errors):
            continue
        if not isinstance(item["path"], str) or not item["path"]:
            errors.append(f"{label}.path must be a non-empty string")
        if not isinstance(item["name"], str):
            errors.append(f"{label}.name must be a string")
        if item["kind"] is not None and not isinstance(item["kind"], str):
            errors.append(f"{label}.kind must be a string or null")
        if item["detection"] is not None and not isinstance(item["detection"], str):
            errors.append(f"{label}.detection must be a string or null")
        if item["status"] not in {"ok", "ready", "missing", "error", "unsupported"}:
            errors.append(f"{label}.status is invalid")
        _check_nonnegative_int(item["bytes"], f"{label}.bytes", errors, nullable=True)
        for key in ("sha256", "source_sha256_before", "source_sha256_after"):
            _check_sha(item[key], f"{label}.{key}", errors)
        if item["source_unchanged"] not in {True, False, None}:
            errors.append(f"{label}.source_unchanged must be boolean or null")
        if item["error"] is not None and not isinstance(item["error"], str):
            errors.append(f"{label}.error must be a string or null")
        if item["entries"] is not None:
            if not isinstance(item["entries"], list):
                errors.append(f"{label}.entries must be an array or null")
            else:
                for entry_index, entry in enumerate(item["entries"]):
                    entry_label = f"{label}.entries[{entry_index}]"
                    if _check_keys(entry, _SCAN_ENTRY_KEYS, entry_label, errors):
                        _check_nonnegative_int(entry["bytes"], f"{entry_label}.bytes", errors)
                        _check_nonnegative_int(entry["compressed_bytes"], f"{entry_label}.compressed_bytes", errors)
                        if not isinstance(entry["is_directory"], bool):
                            errors.append(f"{entry_label}.is_directory must be boolean")
                        if not isinstance(entry["path"], str) or not entry["path"]:
                            errors.append(f"{entry_label}.path must be a non-empty string")
                        if not isinstance(entry["crc32"], str):
                            errors.append(f"{entry_label}.crc32 must be a string")

    outputs = manifest["outputs"]
    outputs_valid = _check_keys(outputs, _OUTPUT_KEYS, "outputs", errors)
    if outputs_valid:
        if outputs["directory"] is not None and not isinstance(outputs["directory"], str):
            errors.append("outputs.directory must be a string or null")
        if not isinstance(outputs["files"], list):
            errors.append("outputs.files must be an array")
        else:
            for index, item in enumerate(outputs["files"]):
                label = f"outputs.files[{index}]"
                if _check_keys(item, _FILE_KEYS, label, errors):
                    if not isinstance(item["path"], str) or not item["path"] or Path(item["path"]).is_absolute() or ".." in Path(item["path"]).parts:
                        errors.append(f"{label}.path must be a relative path without traversal")
                    _check_nonnegative_int(item["bytes"], f"{label}.bytes", errors)
                    _check_sha(item["sha256"], f"{label}.sha256", errors, nullable=False)
        if not isinstance(outputs["count"], int) or isinstance(outputs["count"], bool) or outputs["count"] != len(outputs["files"]):
            errors.append("outputs.count must equal the number of output files")
        if not isinstance(outputs["committed"], bool):
            errors.append("outputs.committed must be boolean")

    entries = manifest["entries"]
    if not isinstance(entries, list):
        errors.append("entries must be an array")
    else:
        for index, item in enumerate(entries):
            label = f"entries[{index}]"
            if not _check_keys_with_optional(item, _ENTRY_KEYS, _ENTRY_OPTIONAL_KEYS, label, errors):
                continue
            for key in ("source", "path", "output_path", "kind", "status"):
                if not isinstance(item[key], str) or not item[key]:
                    errors.append(f"{label}.{key} must be a non-empty string")
            _check_nonnegative_int(item["bytes"], f"{label}.bytes", errors)
            _check_sha(item["sha256"], f"{label}.sha256", errors, nullable=False)
            for key in ("index", "payload_id", "offset", "packed_bytes", "declared_unpacked_bytes", "actual_read_bytes", "actual_unpacked_bytes", "compression_flag"):
                _check_nonnegative_int(item[key], f"{label}.{key}", errors, nullable=True)
            for key in ("bounds_checked", "size_checked", "encrypted"):
                if not isinstance(item[key], bool):
                    errors.append(f"{label}.{key} must be boolean")
            if item["status"] != "ok":
                errors.append(f"{label}.status must be ok for a recorded output")
            if item["actual_unpacked_bytes"] != item["bytes"]:
                errors.append(f"{label}.actual_unpacked_bytes must equal bytes")
            if "asset_id" in item:
                _check_sha(item["asset_id"], f"{label}.asset_id", errors, nullable=False)
            if "source_input_index" in item:
                _check_nonnegative_int(
                    item["source_input_index"], f"{label}.source_input_index", errors
                )
            if "source_sha256" in item:
                _check_sha(item["source_sha256"], f"{label}.source_sha256", errors, nullable=False)
            if "backend" in item and (
                not isinstance(item["backend"], str) or not item["backend"]
            ):
                errors.append(f"{label}.backend must be a non-empty string")
            if "logical_path" in item and item["logical_path"] is not None and (
                not isinstance(item["logical_path"], str) or not item["logical_path"]
            ):
                errors.append(f"{label}.logical_path must be a non-empty string or null")
            for key in ("logical_path_status", "asset_type"):
                if key in item and (not isinstance(item[key], str) or not item[key]):
                    errors.append(f"{label}.{key} must be a non-empty string")
            if "parent_asset_id" in item:
                _check_sha(item["parent_asset_id"], f"{label}.parent_asset_id", errors)

    failures = manifest["failures"]
    if not isinstance(failures, list):
        errors.append("failures must be an array")
    else:
        for index, item in enumerate(failures):
            label = f"failures[{index}]"
            if _check_keys(item, _FAILURE_KEYS, label, errors):
                if not all(isinstance(item[key], str) and item[key] for key in _FAILURE_KEYS):
                    errors.append(f"{label} fields must be non-empty strings")

    claims = manifest["claims"]
    if not isinstance(claims, list):
        errors.append("claims must be an array")
    else:
        for index, item in enumerate(claims):
            label = f"claims[{index}]"
            if _check_keys(item, _CLAIM_KEYS, label, errors):
                if not isinstance(item["claim"], str) or item["certainty"] not in {"fact", "strong_inference", "unknown"}:
                    errors.append(f"{label} has invalid claim fields")

    expected_source_state = _overall_source_state(inputs)
    if manifest["source_unchanged"] != expected_source_state:
        errors.append("source_unchanged does not match per-input source audit states")

    safe_outputs = outputs if isinstance(outputs, dict) else {"directory": None, "files": [], "count": 0, "committed": False}
    safe_files = safe_outputs.get("files") if isinstance(safe_outputs.get("files"), list) else []
    if manifest["operation"] == "scan":
        if safe_outputs.get("committed"):
            errors.append("scan manifests cannot commit an extraction output")
        if manifest["entries"]:
            errors.append("scan manifests must not contain extraction entries")
        if manifest["resume_key"] is not None:
            errors.append("scan manifests must not contain a resume key")
    else:
        if manifest["profile"] not in {"auto", "zip", "nxpk"}:
            errors.append("extract profile must be auto, zip, or nxpk")
        if manifest["strict"] is None:
            errors.append("extract strict must be boolean")
        if manifest["status"] != "failed" and not manifest["resume_key"]:
            errors.append("successful extract manifests must contain a resume key")
        if manifest["status"] == "failed" and safe_outputs.get("committed"):
            errors.append("failed extract manifests cannot commit output")
        if manifest["status"] != "failed" and not safe_outputs.get("committed"):
            errors.append("complete or partial extract manifests must commit output")
        recorded_paths = {item["output_path"] for item in entries if isinstance(item, dict) and "output_path" in item}
        output_paths = {item["path"] for item in safe_files if isinstance(item, dict) and "path" in item}
        if recorded_paths != output_paths:
            errors.append("entries output_path values do not match outputs.files")

    if manifest["status"] == "complete" and manifest["failures"]:
        errors.append("complete manifests cannot contain failures")
    if manifest["status"] == "partial" and not manifest["failures"] and not any(
        item.get("status") in {"unsupported", "missing"} for item in inputs
    ):
        errors.append("partial manifests must contain failures or an explicitly unsupported/missing input")
    if manifest["status"] == "failed" and safe_files:
        errors.append("failed manifests cannot record committed output files")

    if output_root is not None and safe_outputs.get("committed"):
        _validate_output_tree(manifest, Path(output_root), errors)
    return errors
