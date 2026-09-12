from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from zipfile import ZipInfo

from .errors import ExtractionError

_RESERVED_WINDOWS_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"COM{index}" for index in range(1, 10)
} | {f"LPT{index}" for index in range(1, 10)}


def is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_existing_file(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    if path.is_symlink():
        raise ExtractionError(f"symbolic-link input is not allowed: {raw}")
    if not path.exists():
        raise ExtractionError(f"input does not exist: {raw}")
    if not path.is_file():
        raise ExtractionError(f"input is not a file: {raw}")
    return path.resolve()


def resolve_output_path(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    if path.is_symlink():
        raise ExtractionError(f"symbolic-link output path is not allowed: {raw}")
    return path.resolve(strict=False)


def assert_output_disjoint(inputs: list[Path], output: Path) -> None:
    output = output.resolve(strict=False)
    for raw_input in inputs:
        source = raw_input.resolve()
        if source == output or is_within(source, output) or is_within(output, source):
            raise ExtractionError(
                f"output must be disjoint from input: input={source} output={output}"
            )


def normalized_member_name(info: ZipInfo) -> str:
    raw = info.filename.replace("\\", "/")
    if "\x00" in raw or not raw:
        raise ExtractionError(f"unsafe ZIP member name: {info.filename!r}")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        raise ExtractionError(f"absolute ZIP member path is not allowed: {info.filename!r}")
    parts = raw.split("/")
    if info.is_dir() and parts[-1] == "":
        parts = parts[:-1]
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ExtractionError(f"traversal or ambiguous ZIP member path: {info.filename!r}")
    for part in parts:
        if ":" in part:
            raise ExtractionError(f"alternate-data-stream ZIP member path is not allowed: {info.filename!r}")
        stem = part.split(".", 1)[0].upper()
        if stem in _RESERVED_WINDOWS_NAMES:
            raise ExtractionError(f"reserved Windows ZIP member path is not allowed: {info.filename!r}")
    mode = (info.external_attr >> 16) & 0o170000
    if stat.S_ISLNK(mode):
        raise ExtractionError(f"symbolic-link ZIP member is not allowed: {info.filename!r}")
    return "/".join(parts)


def validate_zip_infos(
    infos: list[ZipInfo],
    max_entries: int,
    max_member_bytes: int,
    max_total_bytes: int,
    max_ratio: float,
) -> list[tuple[ZipInfo, str]]:
    if len(infos) > max_entries:
        raise ExtractionError(f"ZIP entry limit exceeded: {len(infos)} > {max_entries}")
    seen: set[str] = set()
    plan: list[tuple[ZipInfo, str]] = []
    total = 0
    for info in infos:
        name = normalized_member_name(info)
        folded = name.casefold()
        if folded in seen:
            raise ExtractionError(f"duplicate or case-colliding ZIP member: {name}")
        seen.add(folded)
        if info.flag_bits & 0x1:
            raise ExtractionError(f"encrypted ZIP member is not supported: {name}")
        if info.file_size > max_member_bytes:
            raise ExtractionError(f"ZIP member limit exceeded: {name}")
        total += info.file_size
        if total > max_total_bytes:
            raise ExtractionError(f"ZIP total output limit exceeded: {total} > {max_total_bytes}")
        if info.file_size:
            if not info.compress_size or info.file_size / info.compress_size > max_ratio:
                raise ExtractionError(f"ZIP compression ratio limit exceeded: {name}")
        plan.append((info, name))
    return plan
