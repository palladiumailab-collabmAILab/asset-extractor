#!/usr/bin/env python3
"""Acquire an immutable, auditable raw-data snapshot from BlueStacks via ADB.

The program only uses read operations (get-state, getprop, find/stat, pm path,
and pull).  It does not request root, use run-as, stop applications, or alter
remote files.  Every invocation requires a new local output directory.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from runtime_artifacts import sha256_file, sha256_json, utc_now, write_json_atomic


VERSION = "0.1.0"
DEFAULT_PACKAGE = "com.netease.onmyoji.na"
DEFAULT_SERIAL = "127.0.0.1:5555"
DEFAULT_REMOTE_TEMPLATE = "/sdcard/Android/data/{package}/files/netease/onmyoji/Documents/OptionRes"
ROOT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")
DEFAULT_MAX_FILES = 50_000
DEFAULT_MAX_FILE_BYTES = 16 * 1024**3
DEFAULT_MAX_TOTAL_BYTES = 64 * 1024**3


class AcquisitionError(RuntimeError):
    """An acquisition precondition or integrity check failed."""


ADB_TIMEOUT_SECONDS = 30 * 60


def resolve_adb(raw: str) -> Path:
    candidate = Path(raw).expanduser()
    resolved = candidate.resolve() if candidate.exists() else None
    if resolved is None:
        found = shutil.which(raw)
        resolved = Path(found).resolve() if found else None
    if resolved is None or not resolved.is_file():
        raise AcquisitionError(f"ADB executable was not found: {raw}")
    return resolved


def run_adb(
    adb: Path,
    serial: str,
    arguments: list[str],
    *,
    text: bool = True,
) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        [str(adb), "-s", serial, *arguments],
        check=True,
        capture_output=True,
        text=text,
        encoding="utf-8" if text else None,
        errors="strict" if text else None,
        timeout=ADB_TIMEOUT_SECONDS,
    )


def validate_remote_path(raw: str) -> str:
    if not raw.startswith("/") or any(character in raw for character in "\r\n\0"):
        raise AcquisitionError(f"remote path must be an absolute POSIX path: {raw!r}")
    path = PurePosixPath(raw)
    if ".." in path.parts or str(path) != raw.rstrip("/"):
        raise AcquisitionError(f"remote path is not canonical: {raw!r}")
    return str(path)


def parse_remote_root(raw: str, package: str) -> tuple[str, str]:
    if "=" not in raw:
        raise AcquisitionError("--remote-root must use NAME=/absolute/device/path")
    name, remote = raw.split("=", 1)
    if not ROOT_NAME_RE.fullmatch(name):
        raise AcquisitionError(f"invalid remote root name: {name!r}")
    try:
        remote = remote.format(package=package)
    except (KeyError, ValueError) as exc:
        raise AcquisitionError(f"invalid remote root template: {raw!r}") from exc
    return name, validate_remote_path(remote)


def validate_package(package: str) -> str:
    if not PACKAGE_RE.fullmatch(package):
        raise AcquisitionError(f"invalid Android package name: {package!r}")
    return package


def parse_inventory_output(remote_root: str, output: str) -> dict[str, dict[str, int]]:
    root = PurePosixPath(remote_root)
    rows: dict[str, dict[str, int]] = {}
    casefolded: set[str] = set()
    for line_number, line in enumerate(output.splitlines(), 1):
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            raise AcquisitionError(f"malformed remote inventory line {line_number}")
        size_text, mtime_text, path_text = parts
        path = PurePosixPath(path_text)
        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise AcquisitionError(f"inventory escaped remote root: {path_text}") from exc
        if relative == PurePosixPath(".") or ".." in relative.parts:
            raise AcquisitionError(f"invalid remote inventory path: {path_text}")
        relative_text = relative.as_posix()
        folded = relative_text.casefold()
        if relative_text in rows or folded in casefolded:
            raise AcquisitionError(f"duplicate or case-colliding remote path: {relative_text}")
        try:
            size = int(size_text)
            mtime = int(mtime_text)
        except ValueError as exc:
            raise AcquisitionError(f"invalid remote metadata for: {path_text}") from exc
        if size < 0 or mtime < 0:
            raise AcquisitionError(f"negative remote metadata for: {path_text}")
        rows[relative_text] = {"size": size, "mtime_unix": mtime}
        casefolded.add(folded)
    return rows


def remote_inventory(adb: Path, serial: str, remote_root: str) -> dict[str, dict[str, int]]:
    command = f"find {shlex.quote(remote_root)} -type f " "-exec stat -c '%s|%Y|%n' {} \\;"
    completed = run_adb(adb, serial, ["shell", command])
    return parse_inventory_output(remote_root, completed.stdout)


def device_properties(adb: Path, serial: str) -> dict[str, str]:
    keys = (
        "ro.product.manufacturer",
        "ro.product.model",
        "ro.build.version.release",
        "ro.build.version.sdk",
        "ro.product.cpu.abilist",
    )
    properties: dict[str, str] = {}
    for key in keys:
        value = run_adb(adb, serial, ["shell", "getprop", key]).stdout.strip()
        properties[key] = value
    return properties


def installed_apk_paths(adb: Path, serial: str, package: str) -> list[str]:
    completed = run_adb(adb, serial, ["shell", "pm", "path", package])
    paths = []
    for line in completed.stdout.splitlines():
        if not line.startswith("package:"):
            continue
        paths.append(validate_remote_path(line.removeprefix("package:").strip()))
    if not paths:
        raise AcquisitionError(f"no installed APK paths were returned for {package}")
    return paths


def remote_file_metadata(adb: Path, serial: str, remote_path: str) -> dict[str, int]:
    command = f"stat -c '%s|%Y' {shlex.quote(remote_path)}"
    output = run_adb(adb, serial, ["shell", command]).stdout.strip()
    parts = output.split("|", 1)
    if len(parts) != 2:
        raise AcquisitionError(f"malformed stat output for {remote_path}")
    try:
        return {"size": int(parts[0]), "mtime_unix": int(parts[1])}
    except ValueError as exc:
        raise AcquisitionError(f"invalid stat output for {remote_path}") from exc


def pull_one(adb: Path, serial: str, remote_path: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f".{destination.name}.partial")
    if partial.exists():
        raise AcquisitionError(f"temporary output already exists: {partial}")
    try:
        run_adb(adb, serial, ["pull", remote_path, str(partial)])
        if not partial.is_file() or partial.is_symlink():
            raise AcquisitionError(f"ADB did not create a regular file: {destination}")
        os.replace(partial, destination)
    finally:
        if partial.exists() and partial.is_file():
            partial.unlink()


def _capture_remote_root(
    *,
    adb: Path,
    serial: str,
    root_name: str,
    remote_root: str,
    output: Path,
    files: list[dict[str, Any]],
    failures: list[dict[str, str]],
    max_files: int,
    max_file_bytes: int,
    max_total_bytes: int,
) -> dict[str, Any]:
    """Pull one configured remote root and append auditable file rows."""

    before = remote_inventory(adb, serial, remote_root)
    planned_bytes = sum(row["size"] for row in before.values())
    largest = max((row["size"] for row in before.values()), default=0)
    if len(files) + len(before) > max_files:
        raise AcquisitionError(f"remote inventory exceeds file limit at {root_name}")
    if largest > max_file_bytes:
        raise AcquisitionError(f"remote inventory exceeds per-file limit at {root_name}")
    if sum(item["bytes"] for item in files) + planned_bytes > max_total_bytes:
        raise AcquisitionError(f"remote inventory exceeds total-byte limit at {root_name}")

    root_failures: list[str] = []
    for relative in sorted(before, key=str.casefold):
        remote_path = f"{remote_root}/{relative}"
        local_path = output / "raw" / root_name / Path(*PurePosixPath(relative).parts)
        try:
            pull_one(adb, serial, remote_path, local_path)
            actual_size = local_path.stat().st_size
            if actual_size != before[relative]["size"]:
                raise AcquisitionError(
                    f"size mismatch after pull: expected {before[relative]['size']}, got {actual_size}"
                )
            digest = sha256_file(local_path)
            files.append(
                {
                    "asset_id": sha256_json(
                        {
                            "serial": serial,
                            "remote_path": remote_path,
                            "size": actual_size,
                            "sha256": digest,
                        }
                    ),
                    "source_kind": "remote-file",
                    "remote_root": root_name,
                    "remote_path": remote_path,
                    "relative_path": relative,
                    "local_path": local_path.relative_to(output).as_posix(),
                    "bytes": actual_size,
                    "sha256": digest,
                    "remote_before": before[relative],
                    "remote_after": None,
                    "remote_unchanged": None,
                    "acquisition_method": "adb-pull-read-only",
                }
            )
        except (OSError, subprocess.CalledProcessError, AcquisitionError) as exc:
            root_failures.append(relative)
            failures.append({"stage": "pull", "source": remote_path, "error": str(exc)})

    after = remote_inventory(adb, serial, remote_root)
    for item in files:
        if item["remote_root"] != root_name:
            continue
        metadata = after.get(item["relative_path"])
        item["remote_after"] = metadata
        item["remote_unchanged"] = metadata == item["remote_before"]
    return {
        "name": root_name,
        "remote_path": remote_root,
        "before_file_count": len(before),
        "after_file_count": len(after),
        "before_total_bytes": sum(row["size"] for row in before.values()),
        "after_total_bytes": sum(row["size"] for row in after.values()),
        "added_during_capture": sorted(set(after) - set(before), key=str.casefold),
        "removed_during_capture": sorted(set(before) - set(after), key=str.casefold),
        "metadata_changed_during_capture": sorted(
            name for name in set(before) & set(after) if before[name] != after[name]
        ),
        "pull_failures": root_failures,
    }


def _capture_installed_apks(
    *,
    adb: Path,
    serial: str,
    package: str,
    output: Path,
    files: list[dict[str, Any]],
    failures: list[dict[str, str]],
    max_files: int,
    max_file_bytes: int,
    max_total_bytes: int,
) -> None:
    """Capture installed APK paths using the same limits and hash contract."""

    for index, remote_path in enumerate(installed_apk_paths(adb, serial, package)):
        name = "base.apk" if index == 0 else f"split-{index:03d}.apk"
        local_path = output / "raw" / "installed-apks" / name
        try:
            before = remote_file_metadata(adb, serial, remote_path)
            if len(files) + 1 > max_files:
                raise AcquisitionError("installed APK capture exceeds file limit")
            if before["size"] > max_file_bytes:
                raise AcquisitionError("installed APK capture exceeds per-file limit")
            if sum(item["bytes"] for item in files) + before["size"] > max_total_bytes:
                raise AcquisitionError("installed APK capture exceeds total-byte limit")
            pull_one(adb, serial, remote_path, local_path)
            after = remote_file_metadata(adb, serial, remote_path)
            digest = sha256_file(local_path)
            if local_path.stat().st_size != before["size"]:
                raise AcquisitionError(f"APK size mismatch after pull: {remote_path}")
            files.append(
                {
                    "asset_id": sha256_json(
                        {
                            "serial": serial,
                            "remote_path": remote_path,
                            "size": local_path.stat().st_size,
                            "sha256": digest,
                        }
                    ),
                    "source_kind": "installed-apk",
                    "remote_root": "installed-apks",
                    "remote_path": remote_path,
                    "relative_path": name,
                    "local_path": local_path.relative_to(output).as_posix(),
                    "bytes": local_path.stat().st_size,
                    "sha256": digest,
                    "remote_before": before,
                    "remote_after": after,
                    "remote_unchanged": before == after,
                    "acquisition_method": "adb-pull-read-only",
                }
            )
        except (OSError, subprocess.CalledProcessError, AcquisitionError) as exc:
            failures.append({"stage": "pull-apk", "source": remote_path, "error": str(exc)})


def _build_snapshot_manifest(
    *,
    started_at: str,
    state: str | None,
    properties: dict[str, str],
    adb_version: str | None,
    adb: Path,
    serial: str,
    package: str,
    remote_roots: list[tuple[str, str]],
    include_apks: bool,
    max_files: int,
    max_file_bytes: int,
    max_total_bytes: int,
    roots_manifest: list[dict[str, Any]],
    files: list[dict[str, Any]],
    failures: list[dict[str, str]],
) -> dict[str, Any]:
    """Build the immutable snapshot record after capture has finished."""

    stable = all(item["remote_unchanged"] is True for item in files)
    roots_stable = all(
        not root["added_during_capture"]
        and not root["removed_during_capture"]
        and not root["metadata_changed_during_capture"]
        and not root["pull_failures"]
        for root in roots_manifest
    )
    status = "complete" if files and stable and roots_stable and not failures else "incomplete"
    return {
        "schema_version": 1,
        "operation": "capture-bluestacks-raw",
        "created_at": started_at,
        "completed_at": utc_now(),
        "status": status,
        "tool": {
            "name": "pull_bluestacks_snapshot.py",
            "version": VERSION,
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "adb": {
            "path": str(adb),
            "version": adb_version,
            "serial": serial,
            "state": state,
            "device_properties": properties,
        },
        "configuration": {
            "package": package,
            "remote_roots": [{"name": name, "path": path} for name, path in remote_roots],
            "include_installed_apks": include_apks,
            "limits": {
                "max_files": max_files,
                "max_file_bytes": max_file_bytes,
                "max_total_bytes": max_total_bytes,
            },
            "configuration_sha256": sha256_json(
                {
                    "package": package,
                    "remote_roots": remote_roots,
                    "include_installed_apks": include_apks,
                    "max_files": max_files,
                    "max_file_bytes": max_file_bytes,
                    "max_total_bytes": max_total_bytes,
                }
            ),
        },
        "policy": {
            "remote_commands_read_only": True,
            "uses_root": False,
            "uses_run_as": False,
            "new_output_directory_required": True,
        },
        "remote_roots": roots_manifest,
        "files": sorted(files, key=lambda item: item["local_path"].casefold()),
        "summary": {
            "files": len(files),
            "bytes": sum(item["bytes"] for item in files),
            "remote_unchanged": sum(item["remote_unchanged"] is True for item in files),
            "remote_changed_or_missing": sum(
                item["remote_unchanged"] is not True for item in files
            ),
            "failures": len(failures),
        },
        "failures": failures,
        "claims": [
            {"certainty": "fact", "text": "Every listed local file has a SHA-256 digest."},
            {
                "certainty": "fact",
                "text": "Remote size and mtime were compared before and after each capture root.",
            },
            {
                "certainty": "scope",
                "text": "Only explicitly configured ADB-readable roots and optional installed APK paths were captured.",
            },
        ],
    }


def snapshot(
    *,
    adb: Path,
    serial: str,
    package: str,
    remote_roots: list[tuple[str, str]],
    output: Path,
    include_apks: bool,
    max_files: int = DEFAULT_MAX_FILES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> dict[str, Any]:
    """Capture configured roots and publish one auditable snapshot manifest."""

    output = output.resolve()
    if output.exists():
        raise AcquisitionError(f"output directory already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()

    started_at = utc_now()
    failures: list[dict[str, str]] = []
    files: list[dict[str, Any]] = []
    roots_manifest: list[dict[str, Any]] = []
    manifest_path = output / "snapshot-manifest.json"
    state: str | None = None
    properties: dict[str, str] = {}
    adb_version: str | None = None

    try:
        state = run_adb(adb, serial, ["get-state"]).stdout.strip()
        if state != "device":
            raise AcquisitionError(f"ADB target is not ready: {state!r}")
        properties = device_properties(adb, serial)
        adb_version = subprocess.run(
            [str(adb), "version"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=ADB_TIMEOUT_SECONDS,
        ).stdout.splitlines()[0]

        for root_name, remote_root in remote_roots:
            roots_manifest.append(
                _capture_remote_root(
                    adb=adb,
                    serial=serial,
                    root_name=root_name,
                    remote_root=remote_root,
                    output=output,
                    files=files,
                    failures=failures,
                    max_files=max_files,
                    max_file_bytes=max_file_bytes,
                    max_total_bytes=max_total_bytes,
                )
            )

        if include_apks:
            _capture_installed_apks(
                adb=adb,
                serial=serial,
                package=package,
                output=output,
                files=files,
                failures=failures,
                max_files=max_files,
                max_file_bytes=max_file_bytes,
                max_total_bytes=max_total_bytes,
            )

    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        AcquisitionError,
    ) as exc:
        failures.append({"stage": "setup-or-inventory", "source": serial, "error": str(exc)})

    manifest = _build_snapshot_manifest(
        started_at=started_at,
        state=state,
        properties=properties,
        adb_version=adb_version,
        adb=adb,
        serial=serial,
        package=package,
        remote_roots=remote_roots,
        include_apks=include_apks,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
        roots_manifest=roots_manifest,
        files=files,
        failures=failures,
    )
    write_json_atomic(manifest_path, manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new snapshot directory")
    parser.add_argument("--adb", default="adb", help="adb executable path or command name")
    parser.add_argument("--serial", default=DEFAULT_SERIAL)
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument(
        "--remote-root",
        action="append",
        default=[],
        metavar="NAME=/PATH",
        help="repeatable remote root; {package} is expanded",
    )
    parser.add_argument("--include-installed-apks", action="store_true")
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--max-total-bytes", type=int, default=DEFAULT_MAX_TOTAL_BYTES)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        adb = resolve_adb(args.adb)
        package = validate_package(args.package)
        if args.max_files <= 0 or args.max_file_bytes <= 0 or args.max_total_bytes <= 0:
            raise AcquisitionError("all acquisition limits must be positive")
        raw_roots = args.remote_root or [f"optionres={DEFAULT_REMOTE_TEMPLATE}"]
        roots = [parse_remote_root(item, package) for item in raw_roots]
        names = [name.casefold() for name, _ in roots]
        if len(names) != len(set(names)):
            raise AcquisitionError("remote root names must be unique")
        manifest = snapshot(
            adb=adb,
            serial=args.serial,
            package=package,
            remote_roots=roots,
            output=args.output,
            include_apks=args.include_installed_apks,
            max_files=args.max_files,
            max_file_bytes=args.max_file_bytes,
            max_total_bytes=args.max_total_bytes,
        )
    except AcquisitionError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "manifest": str(args.output.resolve() / "snapshot-manifest.json"),
                **manifest["summary"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if manifest["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
