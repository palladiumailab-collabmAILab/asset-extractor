from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .errors import ExtractionError


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def config_hash(config: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json(config))


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def file_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not root.exists():
        return rows
    if root.is_symlink():
        raise ExtractionError(f"symbolic-link output root is not allowed: {root}")
    for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for directory in directories:
            path = current_path / directory
            if path.is_symlink():
                raise ExtractionError(f"symbolic-link output directory is not allowed: {path}")
        for filename in filenames:
            path = current_path / filename
            if path.is_symlink():
                raise ExtractionError(f"symbolic-link output file is not allowed: {path}")
            if not path.is_file():
                raise ExtractionError(f"non-regular output is not allowed: {path}")
            if path.stat().st_nlink > 1:
                raise ExtractionError(f"hard-link output is not allowed: {path}")
            relative = path.relative_to(root).as_posix()
            rows.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    rows.sort(key=lambda item: item["path"])
    return rows


def tool_metadata() -> dict[str, str]:
    return {"name": "asset-extractor", "version": __version__}
