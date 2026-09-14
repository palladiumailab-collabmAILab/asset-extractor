from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Any, Callable

from .common import file_rows, sha256_file
from .errors import ExtractionError
from .media_probe import probe_bytes


def _extension(data: bytes) -> str:
    format_id = probe_bytes(data)["format"]
    return {
        "jpeg": "jpg",
        "iso-bmff": "mp4",
        "ebml": "mkv",
        "nxpk": "bin",
        "xml-material": "xml",
        "xml-animation": "xml",
        "xml-scene": "xml",
    }.get(format_id, format_id if format_id != "unknown" else "bin")


_KNOWN_FLAG_MASK = 0x10001


def _checked_span(offset: int, length: int, size: int, label: str) -> int:
    if offset < 0 or length < 0 or offset > size or length > size - offset:
        raise ExtractionError(f"NXPK {label} is outside archive bounds")
    return offset + length


def _read_entries(
    source: Path,
    max_entries: int,
    max_member_bytes: int,
    max_total_bytes: int,
    max_ratio: float,
) -> tuple[int, list[tuple[int, ...]], int]:
    size = source.stat().st_size
    with source.open("rb") as handle:
        # NeoX NPK files use five uint32 values after the magic (24 bytes in
        # total): count, var1, encrypt mode, hash mode, and index offset.  A
        # small legacy fixture used by the repository predates the final
        # value and has a 20-byte header; detect that form only when its index
        # is the only candidate that remains inside the source bounds.
        header = handle.read(24)
        if len(header) < 20 or header[:4] != b"NXPK":
            raise ExtractionError(f"not an NXPK archive: {source}")
        count = struct.unpack_from("<I", header, 4)[0]
        if count > max_entries:
            raise ExtractionError(f"NXPK entry limit exceeded: {count} > {max_entries}")
        candidate_20 = struct.unpack_from("<I", header, 16)[0]
        candidate_24 = struct.unpack_from("<I", header, 20)[0] if len(header) >= 24 else None
        valid_24 = (
            candidate_24 is not None
            and candidate_24 >= 24
            and candidate_24 <= size
            and count <= (size - candidate_24) // 32
        )
        valid_20 = (
            candidate_20 >= 20
            and candidate_20 <= size
            and count <= (size - candidate_20) // 32
        )
        if valid_24 and valid_20:
            raise ExtractionError("ambiguous NXPK header/index layout")
        if valid_24:
            assert candidate_24 is not None
            index_offset = candidate_24
            header_size = 24
        elif valid_20:
            index_offset = candidate_20
            header_size = 20
        else:
            raise ExtractionError("NXPK index exceeds archive size")
        if count and index_offset < header_size:
            raise ExtractionError("NXPK index starts inside archive header")
        if index_offset > size or count > (size - index_offset) // 32:
            raise ExtractionError("NXPK index exceeds archive size")
        handle.seek(index_offset)
        entries: list[tuple[int, ...]] = []
        for index in range(count):
            raw_entry = handle.read(32)
            if len(raw_entry) != 32:
                raise ExtractionError(f"NXPK index entry is truncated at entry {index}")
            entries.append(struct.unpack("<8I", raw_entry))
    total_unpacked = 0
    for entry in entries:
        _, _, offset, packed, unpacked, _, _, flags = entry
        if offset < header_size:
            raise ExtractionError("NXPK entry starts inside archive header")
        _checked_span(offset, packed, size, "entry")
        if packed > max_member_bytes or unpacked > max_member_bytes:
            raise ExtractionError("NXPK member size limit exceeded")
        if flags & ~_KNOWN_FLAG_MASK:
            raise ExtractionError(f"unsupported NXPK flag bits: 0x{flags & ~_KNOWN_FLAG_MASK:x}")
        if flags & 0xFFFF not in {0, 1}:
            raise ExtractionError(f"unsupported NXPK compression flag: {flags & 0xFFFF}")
        if unpacked:
            if not packed or unpacked / packed > max_ratio:
                raise ExtractionError("NXPK compression ratio limit exceeded")
        total_unpacked += unpacked
        if total_unpacked > max_total_bytes:
            raise ExtractionError(
                f"NXPK total output limit exceeded: {total_unpacked} > {max_total_bytes}"
            )
    return count, entries, total_unpacked


def _decompress_exact(data: bytes, expected: int, index: int) -> bytes:
    decoder = zlib.decompressobj()
    try:
        result = decoder.decompress(data, expected + 1)
        if len(result) > expected or decoder.unconsumed_tail:
            raise ExtractionError(f"NXPK expanded size exceeds declaration at entry {index}")
        if len(result) <= expected:
            result += decoder.flush(expected + 1 - len(result))
    except zlib.error as exc:
        raise ExtractionError(f"NXPK zlib decompression failed at entry {index}") from exc
    if not decoder.eof or decoder.unused_data:
        raise ExtractionError(f"NXPK zlib stream is incomplete or has trailing data at entry {index}")
    if len(result) != expected:
        raise ExtractionError(f"NXPK uncompressed size mismatch at entry {index}")
    return result


def _read_payload(handle: Any, entry: tuple[int, ...], index: int) -> tuple[bytes, int]:
    payload_id, _, offset, packed, unpacked, _, _, flags = entry
    handle.seek(offset)
    data = handle.read(packed)
    actual_read = len(data)
    if actual_read != packed:
        raise ExtractionError(
            f"NXPK actual read length mismatch at entry {index}: {actual_read} != {packed}"
        )
    if flags & 0x10000:
        data = bytes(value ^ ((150 + position) % 256) for position, value in enumerate(data[:128])) + data[128:]
    if flags & 0xFFFF == 1:
        data = _decompress_exact(data, unpacked, index)
    if len(data) != unpacked:
        raise ExtractionError(f"NXPK uncompressed size mismatch at entry {index}")
    return data, actual_read


def find_first_nxpk_payload(
    source: Path,
    limits: dict[str, int | float],
    predicate: Callable[[bytes], bool],
) -> dict[str, Any] | None:
    """Return the first decoded payload accepted by ``predicate``.

    The entire index and every payload are still bounds/size/decompression
    checked before success is returned.  Only the selected payload is retained
    in memory; callers can therefore restore one image without publishing the
    complete archive.  The source archive is opened read-only.
    """

    count, entries, declared_total = _read_entries(
        source,
        int(limits["max_entries"]),
        int(limits["max_member_bytes"]),
        int(limits["max_total_bytes"]),
        float(limits["max_ratio"]),
    )
    selected: dict[str, Any] | None = None
    actual_total = 0
    with source.open("rb") as handle:
        for index, entry in enumerate(entries):
            payload_id, _, offset, packed, unpacked, _, _, flags = entry
            data, actual_read = _read_payload(handle, entry, index)
            actual_total += len(data)
            if actual_total > int(limits["max_total_bytes"]):
                raise ExtractionError(
                    f"NXPK total output limit exceeded while reading entry {index}"
                )
            if selected is None and predicate(data):
                selected = {
                    "index": index,
                    "payload_id": payload_id,
                    "offset": offset,
                    "packed_bytes": packed,
                    "declared_unpacked_bytes": unpacked,
                    "actual_read_bytes": actual_read,
                    "actual_unpacked_bytes": len(data),
                    "compression_flag": flags & 0xFFFF,
                    "encrypted": bool(flags & 0x10000),
                    "data": data,
                }
    if actual_total != declared_total:
        raise ExtractionError("NXPK total expanded size mismatch")
    if count != len(entries):
        raise ExtractionError("NXPK entry count changed while scanning")
    return selected


def extract_nxpk(source: Path, destination: Path, limits: dict[str, int | float]) -> dict[str, Any]:
    count, entries, declared_total = _read_entries(
        source,
        int(limits["max_entries"]),
        int(limits["max_member_bytes"]),
        int(limits["max_total_bytes"]),
        float(limits["max_ratio"]),
    )
    destination.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    actual_total = 0
    with source.open("rb") as handle:
        for index, entry in enumerate(entries):
            payload_id, _, offset, packed, unpacked, _, _, flags = entry
            data, actual_read = _read_payload(handle, entry, index)
            actual_total += len(data)
            if actual_total > int(limits["max_total_bytes"]):
                raise ExtractionError(
                    f"NXPK total output limit exceeded while reading entry {index}"
                )
            output = destination / f"{index:07d}_{payload_id:08x}.{_extension(data)}"
            with output.open("xb") as output_stream:
                output_stream.write(data)
            rows.append(
                {
                    "index": index,
                    "path": output.name,
                    "bytes": len(data),
                    "sha256": sha256_file(output),
                    "status": "ok",
                    "payload_id": payload_id,
                    "offset": offset,
                    "packed_bytes": packed,
                    "declared_unpacked_bytes": unpacked,
                    "actual_read_bytes": actual_read,
                    "actual_unpacked_bytes": len(data),
                    "bounds_checked": True,
                    "size_checked": True,
                    "compression_flag": flags & 0xFFFF,
                    "encrypted": bool(flags & 0x10000),
                }
            )
    if actual_total != declared_total:
        raise ExtractionError("NXPK total expanded size mismatch")
    return {
        "entry_count": count,
        "declared_total_unpacked_bytes": declared_total,
        "actual_total_unpacked_bytes": actual_total,
        "entries": rows,
        "files": file_rows(destination),
    }
