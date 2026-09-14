#!/usr/bin/env python3
"""Run a small, Python-only archive extraction and restore verification.

The command intentionally handles only two members: one video and one image.
It uses :mod:`zipfile` for extraction, identifies formats from file signatures,
and compares the hash calculated while reading each archive member with a
second hash of the restored file.  It never invokes an external extractor,
viewer, decoder, shell command, or payload.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
import zipfile
import zlib
from typing import Any, Iterable

from runtime_artifacts import digest_file, sha256_bytes, utc_now


PROGRAMS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROGRAMS_ROOT / "src"))

from asset_extractor.errors import ExtractionError  # noqa: E402
from asset_extractor.nxpk import find_first_nxpk_payload  # noqa: E402


TOOL_NAME = "run_minimal_restore_test"
TOOL_VERSION = "1.0.0"
CHUNK_SIZE = 4 * 1024 * 1024
DETECTION_READ_BYTES = 4096
DEFAULT_MAX_MEMBER_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 1024 * 1024 * 1024
DEFAULT_MAX_RATIO = 10_000.0
DEFAULT_MAX_ARCHIVE_ENTRIES = 500_000

VIDEO_SUFFIXES = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
IMAGE_SUFFIXES = {
    ".bmp",
    ".dds",
    ".gif",
    ".jpeg",
    ".jpg",
    ".ktx",
    ".ktx2",
    ".png",
    ".pvr",
    ".tif",
    ".tiff",
    ".webp",
}
DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


class MinimalRestoreError(RuntimeError):
    """A preflight or restore error that should be recorded in the manifest."""


@dataclass(frozen=True)
class SourceRecord:
    index: int
    path: Path
    expected_sha256: str | None


@dataclass(frozen=True)
class Candidate:
    source_index: int
    source_path: Path
    member: str
    normalized_member: str
    info: zipfile.ZipInfo
    detection: dict[str, Any]
    validation_error: str | None = None


@dataclass(frozen=True)
class NestedCandidate:
    source_index: int
    source_path: Path
    container_member: str
    container_sha256: str
    container_bytes: int
    payload_index: int
    payload_id: int
    payload_offset: int
    packed_bytes: int
    declared_unpacked_bytes: int
    compression_flag: int
    encrypted: bool
    payload: bytes
    detection: dict[str, Any]


def _sha256_file(path: Path) -> tuple[str, int]:
    return digest_file(path, CHUNK_SIZE)


def _normalise_member_name(member: str) -> str:
    """Return a safe, slash-normalised member path or raise.

    We reject traversal and absolute names rather than relying on a filesystem
    resolver.  This keeps the safety property true on both Windows and POSIX.
    """

    if not member or "\x00" in member:
        raise MinimalRestoreError("archive member has an empty or NUL-containing name")
    slash_name = member.replace("\\", "/")
    if slash_name.startswith("/") or slash_name.startswith("//") or DRIVE_PREFIX.match(slash_name):
        raise MinimalRestoreError(f"archive member is absolute: {member!r}")
    raw_parts = slash_name.split("/")
    if any(part == ".." for part in raw_parts):
        raise MinimalRestoreError(f"archive member contains traversal: {member!r}")
    parts = [part for part in raw_parts if part not in {"", "."}]
    if not parts:
        raise MinimalRestoreError(f"archive member has no usable path: {member!r}")
    return "/".join(parts)


def _zip_info_validation(info: zipfile.ZipInfo, limits: dict[str, int | float]) -> str | None:
    try:
        _normalise_member_name(info.filename)
    except MinimalRestoreError as exc:
        return str(exc)
    if info.is_dir():
        return "archive member is a directory"
    mode = (info.external_attr >> 16) & 0o170000
    if stat.S_ISLNK(mode):
        return "archive member is a symbolic link"
    if info.file_size < 0 or info.compress_size < 0:
        return "archive member has a negative size"
    if info.file_size > int(limits["max_member_bytes"]):
        return f"member exceeds limit ({info.file_size} > {limits['max_member_bytes']} bytes)"
    if info.file_size and info.compress_size == 0:
        return "archive member has an invalid zero compressed size"
    if info.compress_size:
        ratio = info.file_size / info.compress_size
        if ratio > float(limits["max_ratio"]):
            return f"member compression ratio exceeds limit ({ratio:.2f} > {limits['max_ratio']})"
    return None


def detect_format_bytes(sample: bytes) -> dict[str, Any]:
    """Detect a container/image format from magic bytes, not its filename."""

    def result(format_id: str, family: str, mime: str, method: str) -> dict[str, Any]:
        return {
            "format": format_id,
            "family": family,
            "mime": mime,
            "method": method,
        }

    if sample.startswith(b"\x89PNG\r\n\x1a\n"):
        return result("png", "image", "image/png", "magic")
    if sample.startswith(b"\xff\xd8\xff"):
        return result("jpeg", "image", "image/jpeg", "magic")
    if sample.startswith((b"GIF87a", b"GIF89a")):
        return result("gif", "image", "image/gif", "magic")
    if sample.startswith(b"BM"):
        return result("bmp", "image", "image/bmp", "magic")
    if sample.startswith((b"II*\x00", b"MM\x00*")):
        return result("tiff", "image", "image/tiff", "magic")
    if len(sample) >= 12 and sample[:4] == b"RIFF" and sample[8:12] == b"WEBP":
        return result("webp", "image", "image/webp", "magic")
    if sample.startswith(b"DDS "):
        return result("dds", "image", "image/vnd-ms.dds", "magic")
    if sample.startswith(b"\xabKTX 11\xbb\r\n\x1a\n"):
        return result("ktx", "image", "image/ktx", "magic")
    if sample.startswith(b"\xabKTX 20\xbb\r\n\x1a\n"):
        return result("ktx2", "image", "image/ktx2", "magic")
    if sample.startswith(b"PVR\x03") or sample.startswith(b"\x03\x00\x00\x00") and len(sample) >= 52:
        return result("pvr", "image", "image/x-pvr", "magic")

    if len(sample) >= 12 and sample[4:8] == b"ftyp":
        return result("iso-bmff", "video", "video/mp4", "magic")
    if len(sample) >= 12 and sample[:4] == b"RIFF" and sample[8:12] == b"AVI ":
        return result("avi", "video", "video/x-msvideo", "magic")
    if sample.startswith(b"\x1a\x45\xdf\xa3"):
        return result("ebml", "video", "video/x-matroska", "magic")

    return result("unknown", "unknown", "application/octet-stream", "unrecognised")


def _member_sample(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    with archive.open(info, "r") as stream:
        return stream.read(DETECTION_READ_BYTES)


def _candidate_sort_key(candidate: Candidate) -> tuple[int, str, str]:
    return (
        candidate.source_index,
        candidate.normalized_member.casefold(),
        candidate.normalized_member,
    )


def _candidate_matches_member(candidate: Candidate, requested: str) -> bool:
    try:
        normalized_requested = _normalise_member_name(requested)
    except MinimalRestoreError:
        return False
    return candidate.normalized_member == normalized_requested


def _select_candidate(
    kind: str,
    candidates: list[Candidate],
    requested_member: str | None,
) -> tuple[Candidate | None, list[str]]:
    failures: list[str] = []
    if requested_member is not None:
        matching = [candidate for candidate in candidates if _candidate_matches_member(candidate, requested_member)]
        if not matching:
            failures.append(f"requested {kind} member was not found: {requested_member}")
            return None, failures
        if len(matching) > 1:
            failures.append(f"requested {kind} member is ambiguous across source archives: {requested_member}")
            return None, failures
        candidate = matching[0]
        if candidate.validation_error:
            failures.append(f"requested {kind} member rejected: {candidate.validation_error}")
            return None, failures
        if candidate.detection["family"] != kind:
            failures.append(
                f"requested {kind} member has detected family {candidate.detection['family']}: "
                f"{candidate.normalized_member}"
            )
            return None, failures
        return candidate, failures

    for candidate in sorted(candidates, key=_candidate_sort_key):
        if candidate.validation_error:
            failures.append(f"skipped {candidate.normalized_member}: {candidate.validation_error}")
            continue
        if candidate.detection["family"] == kind:
            return candidate, failures
        failures.append(
            f"skipped {candidate.normalized_member}: detected family {candidate.detection['family']}"
        )
    failures.append(f"no valid {kind} member was found")
    return None, failures


def _safe_output_name(kind: str, candidate: Candidate) -> str:
    basename = PurePosixPath(candidate.normalized_member).name
    basename = re.sub(r"[^A-Za-z0-9._-]+", "_", basename).strip(" .") or f"restored.{kind}"
    if basename.upper().split(".", 1)[0] in {
        "AUX",
        "CON",
        "NUL",
        "PRN",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "LPT1",
        "LPT2",
        "LPT3",
    }:
        basename = f"_{basename}"
    return f"{candidate.source_index:02d}-{basename}"


def _copy_zip_member_to_path(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    target: Path,
    limits: dict[str, int | float],
) -> tuple[str, int]:
    validation_error = _zip_info_validation(info, limits)
    if validation_error:
        raise MinimalRestoreError(validation_error)
    digest = hashlib.sha256()
    crc = 0
    size = 0
    with archive.open(info, "r") as source_stream, target.open("wb") as output_stream:
        while True:
            block = source_stream.read(CHUNK_SIZE)
            if not block:
                break
            output_stream.write(block)
            digest.update(block)
            crc = zlib.crc32(block, crc)
            size += len(block)
        output_stream.flush()
        os.fsync(output_stream.fileno())
    if size != info.file_size:
        raise MinimalRestoreError(f"nested archive size mismatch: {size} != {info.file_size}")
    if (crc & 0xFFFFFFFF) != (info.CRC & 0xFFFFFFFF):
        raise MinimalRestoreError("nested archive CRC-32 mismatch")
    return digest.hexdigest(), size


def _find_nested_nxpk_image(
    sources: list[SourceRecord],
    output_dir: Path,
    limits: dict[str, int | float],
) -> tuple[NestedCandidate | None, list[str]]:
    containers: list[tuple[int, SourceRecord, zipfile.ZipInfo, str]] = []
    rejections: list[str] = []
    for record in sources:
        if not record.path.is_file():
            continue
        try:
            with zipfile.ZipFile(record.path, "r") as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    try:
                        normalized = _normalise_member_name(info.filename)
                    except MinimalRestoreError as exc:
                        if info.filename.lower().endswith(".npk"):
                            rejections.append(f"skipped nested {info.filename}: {exc}")
                        continue
                    if PurePosixPath(normalized).suffix.lower() == ".npk":
                        containers.append((info.file_size, record, info, normalized))
        except (OSError, zipfile.BadZipFile) as exc:
            rejections.append(f"cannot enumerate nested archives in {record.path}: {exc}")

    for _declared_size, record, info, normalized in sorted(
        containers,
        key=lambda item: (item[0], item[1].index, item[3].casefold(), item[3]),
    ):
        validation_error = _zip_info_validation(info, limits)
        if validation_error:
            rejections.append(f"skipped nested {normalized}: {validation_error}")
            continue
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=".minimal-restore-nested-",
                suffix=".npk",
                dir=output_dir,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
            with zipfile.ZipFile(record.path, "r") as archive:
                container_sha256, container_bytes = _copy_zip_member_to_path(
                    archive,
                    info,
                    temporary_path,
                    limits,
                )
            nxpk_limits = {
                "max_entries": DEFAULT_MAX_ARCHIVE_ENTRIES,
                "max_member_bytes": limits["max_member_bytes"],
                "max_total_bytes": limits["max_total_bytes"],
                "max_ratio": limits["max_ratio"],
            }
            match = find_first_nxpk_payload(
                temporary_path,
                nxpk_limits,
                lambda payload: detect_format_bytes(payload[:DETECTION_READ_BYTES])["family"] == "image",
            )
            if match is None:
                rejections.append(f"nested archive has no recognised image payload: {normalized}")
                continue
            payload = match["data"]
            detection = detect_format_bytes(payload[:DETECTION_READ_BYTES])
            return (
                NestedCandidate(
                    source_index=record.index,
                    source_path=record.path,
                    container_member=normalized,
                    container_sha256=container_sha256,
                    container_bytes=container_bytes,
                    payload_index=int(match["index"]),
                    payload_id=int(match["payload_id"]),
                    payload_offset=int(match["offset"]),
                    packed_bytes=int(match["packed_bytes"]),
                    declared_unpacked_bytes=int(match["declared_unpacked_bytes"]),
                    compression_flag=int(match["compression_flag"]),
                    encrypted=bool(match["encrypted"]),
                    payload=payload,
                    detection=detection,
                ),
                rejections,
            )
        except (OSError, RuntimeError, ValueError, ExtractionError, MinimalRestoreError) as exc:
            rejections.append(f"nested archive failed validation {normalized}: {exc}")
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
    rejections.append("no valid image payload was found in nested NXPK archives")
    return None, rejections


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _extract_candidate(
    candidate: Candidate,
    output_dir: Path,
    kind: str,
    limits: dict[str, int | float],
) -> dict[str, Any]:
    if candidate.validation_error:
        raise MinimalRestoreError(candidate.validation_error)
    info = candidate.info
    validation_error = _zip_info_validation(info, limits)
    if validation_error:
        raise MinimalRestoreError(validation_error)

    target = output_dir / "restored" / kind / _safe_output_name(kind, candidate)
    if not _path_is_within(target, output_dir):
        raise MinimalRestoreError("restored output path escaped the run directory")
    target.parent.mkdir(parents=True, exist_ok=False)
    partial = target.with_name(target.name + ".partial")
    member_digest = hashlib.sha256()
    member_crc = 0
    member_bytes = 0
    try:
        with zipfile.ZipFile(candidate.source_path, "r") as archive:
            with archive.open(info, "r") as source_stream, partial.open("xb") as output_stream:
                while True:
                    block = source_stream.read(CHUNK_SIZE)
                    if not block:
                        break
                    output_stream.write(block)
                    member_digest.update(block)
                    member_crc = zlib.crc32(block, member_crc)
                    member_bytes += len(block)
                output_stream.flush()
                os.fsync(output_stream.fileno())
        if member_bytes != info.file_size:
            raise MinimalRestoreError(
                f"member size mismatch after reading: {member_bytes} != {info.file_size}"
            )
        member_sha256 = member_digest.hexdigest()
        member_crc_hex = f"{member_crc & 0xFFFFFFFF:08x}"
        expected_crc_hex = f"{info.CRC & 0xFFFFFFFF:08x}"
        if member_crc_hex != expected_crc_hex:
            raise MinimalRestoreError(
                f"member CRC mismatch after reading: {member_crc_hex} != {expected_crc_hex}"
            )
        partial.replace(target)
    finally:
        if partial.exists():
            partial.unlink()

    restored_sha256, restored_bytes = _sha256_file(target)
    with target.open("rb") as restored_stream:
        restored_detection = detect_format_bytes(restored_stream.read(DETECTION_READ_BYTES))
    hash_match = member_sha256 == restored_sha256
    bytes_match = member_bytes == restored_bytes
    format_match = (
        candidate.detection["family"] == restored_detection["family"]
        and candidate.detection["format"] == restored_detection["format"]
    )
    complete = hash_match and bytes_match and format_match and member_crc_hex == expected_crc_hex
    if not complete:
        raise MinimalRestoreError(
            "restored verification failed: "
            f"hash_match={hash_match}, bytes_match={bytes_match}, format_match={format_match}"
        )
    return {
        "kind": kind,
        "nested": False,
        "source_index": candidate.source_index,
        "source_archive": str(candidate.source_path),
        "member": candidate.normalized_member,
        "output": str(target),
        "zip_member_bytes": info.file_size,
        "restored_bytes": restored_bytes,
        "zip_crc32": expected_crc_hex,
        "read_crc32": member_crc_hex,
        "source_member_sha256": member_sha256,
        "restored_sha256": restored_sha256,
        "hash_match": hash_match,
        "bytes_match": bytes_match,
        "source_detection": candidate.detection,
        "restored_detection": restored_detection,
        "format_match": format_match,
        "status": "complete",
    }


def _extract_nested_candidate(
    candidate: NestedCandidate,
    output_dir: Path,
) -> dict[str, Any]:
    suffix = candidate.detection["format"]
    if suffix == "iso-bmff":
        suffix = "mp4"
    target = (
        output_dir
        / "restored"
        / "image"
        / f"{candidate.source_index:02d}-{PurePosixPath(candidate.container_member).stem}"
        f"-entry-{candidate.payload_index:07d}.{suffix}"
    )
    if not _path_is_within(target, output_dir):
        raise MinimalRestoreError("restored nested output path escaped the run directory")
    target.parent.mkdir(parents=True, exist_ok=False)
    partial = target.with_name(target.name + ".partial")
    payload_sha256 = sha256_bytes(candidate.payload)
    payload_crc32 = f"{zlib.crc32(candidate.payload) & 0xFFFFFFFF:08x}"
    try:
        with partial.open("xb") as output_stream:
            output_stream.write(candidate.payload)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        partial.replace(target)
    finally:
        if partial.exists():
            partial.unlink()

    restored_sha256, restored_bytes = _sha256_file(target)
    with target.open("rb") as restored_stream:
        restored_detection = detect_format_bytes(restored_stream.read(DETECTION_READ_BYTES))
    hash_match = payload_sha256 == restored_sha256
    bytes_match = len(candidate.payload) == restored_bytes
    format_match = (
        candidate.detection["family"] == restored_detection["family"]
        and candidate.detection["format"] == restored_detection["format"]
    )
    if not hash_match or not bytes_match or not format_match:
        raise MinimalRestoreError(
            "restored nested verification failed: "
            f"hash_match={hash_match}, bytes_match={bytes_match}, format_match={format_match}"
        )
    member = (
        f"{candidate.container_member}::entry/"
        f"{candidate.payload_index:07d}_{candidate.payload_id:08x}.{suffix}"
    )
    return {
        "kind": "image",
        "nested": True,
        "source_index": candidate.source_index,
        "source_archive": str(candidate.source_path),
        "member": member,
        "container_member": candidate.container_member,
        "container_sha256": candidate.container_sha256,
        "container_bytes": candidate.container_bytes,
        "nested_entry_index": candidate.payload_index,
        "nested_payload_id": candidate.payload_id,
        "nested_payload_offset": candidate.payload_offset,
        "nested_packed_bytes": candidate.packed_bytes,
        "nested_declared_unpacked_bytes": candidate.declared_unpacked_bytes,
        "nested_compression_flag": candidate.compression_flag,
        "nested_encrypted": candidate.encrypted,
        "output": str(target),
        "zip_member_bytes": len(candidate.payload),
        "restored_bytes": restored_bytes,
        "zip_crc32": None,
        "read_crc32": payload_crc32,
        "source_member_sha256": payload_sha256,
        "restored_sha256": restored_sha256,
        "hash_match": hash_match,
        "bytes_match": bytes_match,
        "source_detection": candidate.detection,
        "restored_detection": restored_detection,
        "format_match": format_match,
        "status": "complete",
    }


def _new_source_row(record: SourceRecord) -> dict[str, Any]:
    return {
        "index": record.index,
        "path": str(record.path),
        "name": record.path.name,
        "bytes": None,
        "sha256_before": None,
        "sha256_after": None,
        "source_unchanged": None,
        "expected_sha256": record.expected_sha256,
        "expected_match": None,
        "archive_entries": None,
        "status": "pending",
        "error": None,
    }


def _new_manifest(
    sources: list[SourceRecord],
    output_dir: Path,
    limits: dict[str, int | float],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": "minimal-archive-restore-test",
        "created_at": utc_now(),
        "status": "failed",
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION, "python": sys.version.split()[0]},
        "policy": {
            "python_only": True,
            "external_commands": False,
            "payload_execution": False,
            "source_read_only": True,
        },
        "output_directory": str(output_dir),
        "limits": limits,
        "sources": [_new_source_row(source) for source in sources],
        "selection": {
            "video": None,
            "image": None,
            "candidate_rejections": {"video": [], "image": []},
        },
        "assets": [],
        "source_unchanged": None,
        "failures": [],
        "summary": {
            "assets_requested": 2,
            "assets_completed": 0,
            "hashes_verified": 0,
            "formats_verified": 0,
        },
    }


def _write_manifest(output_dir: Path, manifest: dict[str, Any]) -> Path:
    manifest_path = output_dir / "minimal-restore-manifest.json"
    partial = output_dir / ".minimal-restore-manifest.json.partial"
    with partial.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    partial.replace(manifest_path)
    return manifest_path


def _record_failure(manifest: dict[str, Any], path: str, stage: str, error: str) -> None:
    manifest["failures"].append({"path": path, "stage": stage, "error": error})


def _source_candidates(
    record: SourceRecord,
    source_row: dict[str, Any],
    limits: dict[str, int | float],
) -> tuple[list[Candidate], list[Candidate]]:
    videos: list[Candidate] = []
    images: list[Candidate] = []
    with zipfile.ZipFile(record.path, "r") as archive:
        infos = archive.infolist()
        source_row["archive_entries"] = len(infos)
        if len(infos) > DEFAULT_MAX_ARCHIVE_ENTRIES:
            raise MinimalRestoreError(
                f"archive has too many entries ({len(infos)} > {DEFAULT_MAX_ARCHIVE_ENTRIES})"
            )
        for info in infos:
            if info.is_dir():
                continue
            try:
                normalized = _normalise_member_name(info.filename)
            except MinimalRestoreError as exc:
                # Only candidate files matter for this minimal run.  Keep the
                # rejection visible if a malformed member has a target suffix.
                suffix = PurePosixPath(info.filename.replace("\\", "/")).suffix.lower()
                if suffix in VIDEO_SUFFIXES or suffix in IMAGE_SUFFIXES:
                    candidate = Candidate(
                        record.index,
                        record.path,
                        info.filename,
                        info.filename,
                        info,
                        detect_format_bytes(b""),
                        str(exc),
                    )
                    (videos if suffix in VIDEO_SUFFIXES else images).append(candidate)
                continue
            suffix = PurePosixPath(normalized).suffix.lower()
            if suffix not in VIDEO_SUFFIXES and suffix not in IMAGE_SUFFIXES:
                continue
            validation_error = _zip_info_validation(info, limits)
            detection: dict[str, Any]
            if validation_error:
                detection = detect_format_bytes(b"")
            else:
                try:
                    detection = detect_format_bytes(_member_sample(archive, info))
                except (OSError, RuntimeError, zipfile.BadZipFile, ValueError) as exc:
                    validation_error = f"cannot read member header: {exc}"
                    detection = detect_format_bytes(b"")
            candidate = Candidate(
                record.index,
                record.path,
                info.filename,
                normalized,
                info,
                detection,
                validation_error,
            )
            if suffix in VIDEO_SUFFIXES:
                videos.append(candidate)
            else:
                images.append(candidate)
    return videos, images


def _verify_sources_after(
    sources: list[SourceRecord],
    source_rows: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> None:
    all_unchanged = True
    for record, row in zip(sources, source_rows):
        if row["sha256_before"] is None:
            all_unchanged = False
            continue
        try:
            after_sha256, after_bytes = _sha256_file(record.path)
            row["sha256_after"] = after_sha256
            if row["bytes"] is not None and after_bytes != row["bytes"]:
                row["source_unchanged"] = False
            else:
                row["source_unchanged"] = after_sha256 == row["sha256_before"]
            if not row["source_unchanged"]:
                _record_failure(
                    manifest,
                    str(record.path),
                    "source-post-hash",
                    "source archive changed during the test",
                )
                all_unchanged = False
        except (OSError, PermissionError) as exc:
            row["status"] = "error"
            row["error"] = f"cannot hash source after extraction: {exc}"
            row["source_unchanged"] = False
            _record_failure(manifest, str(record.path), "source-post-hash", row["error"])
            all_unchanged = False
    manifest["source_unchanged"] = all_unchanged if source_rows else None


def _prepare_run(
    source_paths: Iterable[str | os.PathLike[str]],
    output_dir: str | os.PathLike[str],
    expected_source_sha256: Iterable[str] | None,
    max_member_bytes: int,
    max_total_bytes: int,
    max_ratio: float,
) -> tuple[list[SourceRecord], Path, dict[str, int | float]]:
    """Validate run arguments and create the new output directory."""

    paths = [Path(path).expanduser().resolve() for path in source_paths]
    if not paths:
        raise MinimalRestoreError("at least one --source is required")
    output = Path(output_dir).expanduser().resolve()
    if output.exists():
        raise MinimalRestoreError(f"output directory already exists; use a new run: {output}")
    if any(output == path for path in paths):
        raise MinimalRestoreError("output directory cannot be the source archive")
    expected = list(expected_source_sha256 or [])
    if expected and len(expected) != len(paths):
        raise MinimalRestoreError(
            "--expected-source-sha256 must be supplied once for every --source"
        )
    for digest in expected:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise MinimalRestoreError(f"invalid expected SHA-256: {digest}")

    limits: dict[str, int | float] = {
        "max_member_bytes": max_member_bytes,
        "max_total_bytes": max_total_bytes,
        "max_ratio": max_ratio,
    }
    if max_member_bytes <= 0 or max_total_bytes <= 0 or max_ratio <= 0:
        raise MinimalRestoreError("all extraction limits must be positive")

    records = [
        SourceRecord(index, path, (expected[index].lower() if expected else None))
        for index, path in enumerate(paths)
    ]
    output.mkdir(parents=True, exist_ok=False)
    return records, output, limits


def _preflight_sources(
    records: list[SourceRecord],
    source_rows: list[dict[str, Any]],
    limits: dict[str, int | float],
    manifest: dict[str, Any],
) -> tuple[list[Candidate], list[Candidate]]:
    """Hash, inspect, and enumerate candidate members from each source."""

    video_candidates: list[Candidate] = []
    image_candidates: list[Candidate] = []
    for record, row in zip(records, source_rows):
        if not record.path.exists():
            row["status"] = "missing"
            row["error"] = "source archive does not exist"
            _record_failure(manifest, str(record.path), "source-preflight", row["error"])
            continue
        if not record.path.is_file() or record.path.is_symlink():
            row["status"] = "error"
            row["error"] = "source must be a regular non-symlink file"
            _record_failure(manifest, str(record.path), "source-preflight", row["error"])
            continue
        try:
            sha256_before, source_bytes = _sha256_file(record.path)
            row["bytes"] = source_bytes
            row["sha256_before"] = sha256_before
            row["expected_match"] = (
                record.expected_sha256 is None or sha256_before == record.expected_sha256
            )
            if not row["expected_match"]:
                row["status"] = "error"
                row["error"] = "source SHA-256 did not match the expected provenance hash"
                _record_failure(manifest, str(record.path), "source-preflight", row["error"])
                continue
            source_videos, source_images = _source_candidates(record, row, limits)
            video_candidates.extend(source_videos)
            image_candidates.extend(source_images)
            row["status"] = "ready"
        except (OSError, PermissionError, zipfile.BadZipFile, RuntimeError, ValueError) as exc:
            row["status"] = "error"
            row["error"] = str(exc)
            _record_failure(manifest, str(record.path), "source-preflight", row["error"])
    return video_candidates, image_candidates


def _selection_record(candidate: Candidate | NestedCandidate) -> dict[str, Any]:
    """Serialize a selected direct or nested candidate for the manifest."""

    if isinstance(candidate, Candidate):
        return {
            "source_index": candidate.source_index,
            "source_archive": str(candidate.source_path),
            "member": candidate.normalized_member,
            "declared_bytes": candidate.info.file_size,
            "compressed_bytes": candidate.info.compress_size,
            "crc32": f"{candidate.info.CRC & 0xFFFFFFFF:08x}",
            "detection": candidate.detection,
            "nested": False,
        }
    nested_member = (
        f"{candidate.container_member}::entry/"
        f"{candidate.payload_index:07d}_{candidate.payload_id:08x}."
        f"{candidate.detection['format']}"
    )
    return {
        "source_index": candidate.source_index,
        "source_archive": str(candidate.source_path),
        "member": nested_member,
        "declared_bytes": len(candidate.payload),
        "compressed_bytes": candidate.packed_bytes,
        "crc32": None,
        "detection": candidate.detection,
        "nested": True,
        "container_member": candidate.container_member,
        "container_sha256": candidate.container_sha256,
        "nested_entry_index": candidate.payload_index,
        "nested_payload_id": candidate.payload_id,
    }


def _select_and_record_assets(
    *,
    records: list[SourceRecord],
    output: Path,
    limits: dict[str, int | float],
    video_candidates: list[Candidate],
    image_candidates: list[Candidate],
    video_member: str | None,
    image_member: str | None,
    manifest: dict[str, Any],
) -> tuple[Candidate | None, Candidate | NestedCandidate | None]:
    """Select video/image candidates, including the nested-NXPK fallback."""

    selected_video, video_failures = _select_candidate("video", video_candidates, video_member)
    selected_direct_image, image_failures = _select_candidate("image", image_candidates, image_member)
    selected_image: Candidate | NestedCandidate | None = selected_direct_image
    if selected_image is None and image_member is None:
        nested_image, nested_failures = _find_nested_nxpk_image(records, output, limits)
        image_failures.extend(nested_failures)
        selected_image = nested_image

    manifest["selection"]["candidate_rejections"]["video"] = video_failures
    manifest["selection"]["candidate_rejections"]["image"] = image_failures
    if selected_video is not None:
        manifest["selection"]["video"] = _selection_record(selected_video)
    else:
        _record_failure(manifest, "video", "selection", "; ".join(video_failures))
    if selected_image is not None:
        manifest["selection"]["image"] = _selection_record(selected_image)
    else:
        _record_failure(manifest, "image", "selection", "; ".join(image_failures))
    return selected_video, selected_image


def _restore_selected_assets(
    selected_video: Candidate | None,
    selected_image: Candidate | NestedCandidate | None,
    output: Path,
    limits: dict[str, int | float],
    manifest: dict[str, Any],
) -> None:
    """Restore both selected members or record the first restore failure."""

    if selected_video is None or selected_image is None:
        return
    selected_assets = [("video", selected_video), ("image", selected_image)]
    total_selected_bytes = sum(
        candidate.info.file_size if isinstance(candidate, Candidate) else len(candidate.payload)
        for _, candidate in selected_assets
    )
    if total_selected_bytes > limits["max_total_bytes"]:
        _record_failure(
            manifest,
            "selection",
            "limits",
            f"selected members exceed total output limit ({total_selected_bytes} > {limits['max_total_bytes']})",
        )
        return

    for kind, candidate in selected_assets:
        try:
            if isinstance(candidate, NestedCandidate):
                asset = _extract_nested_candidate(candidate, output)
            else:
                asset = _extract_candidate(candidate, output, kind, limits)
            manifest["assets"].append(asset)
        except (OSError, PermissionError, RuntimeError, ValueError, MinimalRestoreError) as exc:
            member_name = (
                candidate.container_member
                if isinstance(candidate, NestedCandidate)
                else candidate.normalized_member
            )
            _record_failure(manifest, member_name, "restore", str(exc))
            break


def _finalize_manifest(output: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Derive summary/status from verified assets and publish the manifest."""

    completed_assets = [asset for asset in manifest["assets"] if asset.get("status") == "complete"]
    manifest["summary"]["assets_completed"] = len(completed_assets)
    manifest["summary"]["hashes_verified"] = sum(1 for asset in completed_assets if asset["hash_match"])
    manifest["summary"]["formats_verified"] = sum(1 for asset in completed_assets if asset["format_match"])
    if (
        len(completed_assets) == 2
        and manifest["summary"]["hashes_verified"] == 2
        and manifest["summary"]["formats_verified"] == 2
        and manifest["source_unchanged"] is True
        and not manifest["failures"]
    ):
        manifest["status"] = "complete"
    elif completed_assets:
        manifest["status"] = "partial"
    else:
        manifest["status"] = "failed"
    _write_manifest(output, manifest)
    return manifest


def run_minimal_restore_test(
    source_paths: Iterable[str | os.PathLike[str]],
    output_dir: str | os.PathLike[str],
    *,
    video_member: str | None = None,
    image_member: str | None = None,
    expected_source_sha256: Iterable[str] | None = None,
    max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_ratio: float = DEFAULT_MAX_RATIO,
) -> dict[str, Any]:
    """Run the Python-only two-member test and return its manifest object."""

    records, output, limits = _prepare_run(
        source_paths,
        output_dir,
        expected_source_sha256,
        max_member_bytes,
        max_total_bytes,
        max_ratio,
    )
    manifest = _new_manifest(records, output, limits)
    source_rows = manifest["sources"]

    try:
        video_candidates, image_candidates = _preflight_sources(
            records, source_rows, limits, manifest
        )
        selected_video, selected_image = _select_and_record_assets(
            records=records,
            output=output,
            limits=limits,
            video_candidates=video_candidates,
            image_candidates=image_candidates,
            video_member=video_member,
            image_member=image_member,
            manifest=manifest,
        )
        _restore_selected_assets(selected_video, selected_image, output, limits, manifest)
    finally:
        _verify_sources_after(records, source_rows, manifest)
    return _finalize_manifest(output, manifest)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True, help="read-only ZIP/OBB source; repeatable")
    parser.add_argument("--output", required=True, help="new run directory; it must not already exist")
    parser.add_argument("--video-member", help="exact archive member to use for the video")
    parser.add_argument("--image-member", help="exact archive member to use for the image")
    parser.add_argument(
        "--expected-source-sha256",
        action="append",
        help="expected source SHA-256, once per --source, in the same order",
    )
    parser.add_argument("--max-member-bytes", type=int, default=DEFAULT_MAX_MEMBER_BYTES)
    parser.add_argument("--max-total-bytes", type=int, default=DEFAULT_MAX_TOTAL_BYTES)
    parser.add_argument("--max-ratio", type=float, default=DEFAULT_MAX_RATIO)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        manifest = run_minimal_restore_test(
            args.source,
            args.output,
            video_member=args.video_member,
            image_member=args.image_member,
            expected_source_sha256=args.expected_source_sha256,
            max_member_bytes=args.max_member_bytes,
            max_total_bytes=args.max_total_bytes,
            max_ratio=args.max_ratio,
        )
    except MinimalRestoreError as exc:
        print(f"minimal restore test could not start: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "output_directory": manifest["output_directory"],
                "manifest": str(Path(manifest["output_directory"]) / "minimal-restore-manifest.json"),
                "assets_completed": manifest["summary"]["assets_completed"],
                "hashes_verified": manifest["summary"]["hashes_verified"],
                "formats_verified": manifest["summary"]["formats_verified"],
                "source_unchanged": manifest["source_unchanged"],
            },
            ensure_ascii=False,
        )
    )
    return {"complete": 0, "partial": 1, "failed": 2}[manifest["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
