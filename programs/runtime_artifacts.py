"""Shared hashing, timestamp, and atomic artifact helpers for entrypoints.

The maintained command-line programs are executable directly from the
``programs`` directory, so this module deliberately has no package import
bootstrap or third-party dependency.  Helpers are deterministic where the
caller provides the input and keep partial files out of published output
trees when serialization or replacement fails.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_HASH_CHUNK_SIZE = 4 * 1024 * 1024


def utc_now() -> str:
    """Return a compact UTC timestamp suitable for a manifest field."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def digest_file(path: Path, chunk_size: int = DEFAULT_HASH_CHUNK_SIZE) -> tuple[str, int]:
    """Return a file's SHA-256 and byte count from one read pass."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def sha256_file(path: Path, chunk_size: int = DEFAULT_HASH_CHUNK_SIZE) -> str:
    """Return a file's SHA-256 without loading it all into memory."""

    return digest_file(path, chunk_size)[0]


def sha256_bytes(data: bytes) -> str:
    """Return the SHA-256 of bytes."""

    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    """Serialize a value for stable content-addressed metadata."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sha256_json(value: Any) -> str:
    """Return the SHA-256 of canonical JSON."""

    return sha256_bytes(canonical_json(value))


def json_bytes(value: Any) -> bytes:
    """Serialize a human-readable JSON artifact with a trailing newline."""

    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_bytes_atomic(path: Path, data: bytes, *, overwrite: bool = True) -> None:
    """Write bytes through a same-directory fsynced temporary file.

    When ``overwrite`` is false, both the preflight and replacement windows
    reject an existing regular file or symlink.  The latter check protects the
    no-overwrite contract from a concurrent creator without leaving a partial
    file behind.
    """

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and (path.exists() or path.is_symlink()):
        raise FileExistsError(path)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".partial",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if not overwrite and (path.exists() or path.is_symlink()):
            raise FileExistsError(path)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json_atomic(path: Path, value: Any, *, overwrite: bool = True) -> None:
    """Serialize and atomically publish a JSON artifact."""

    write_bytes_atomic(path, json_bytes(value), overwrite=overwrite)
