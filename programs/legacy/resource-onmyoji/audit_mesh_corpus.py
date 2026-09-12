"""Audit every distinct extracted NeoX .mesh without changing source data."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parent
SOURCE_TREE = TOOL_ROOT / "NeoXtractor-source-v3.2"
sys.path.insert(0, str(SOURCE_TREE))

from core.mesh_loader.parsers.new_parser import MeshParser0  # noqa: E402


def header(data: bytes) -> dict[str, int | str | None]:
    if len(data) < 12:
        return {"magic": None, "version": None, "bone_type": None}
    magic, version, marker, bone_type, reserved = struct.unpack_from("<IHHHH", data)
    return {
        "magic": f"0x{magic:08x}",
        "version": version,
        "marker": marker,
        "bone_type": bone_type,
        "reserved": reserved,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    paths = sorted(
        {path.resolve() for root in args.roots for path in root.resolve().rglob("*.mesh")},
        key=lambda path: str(path).lower(),
    )
    seen: dict[str, str] = {}
    failures: list[dict] = []
    counts = Counter()
    parser0 = MeshParser0()

    for index, path in enumerate(paths, 1):
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            counts["duplicate_files"] += 1
            continue
        seen[digest] = str(path)
        info = header(data)
        counts["unique_payloads"] += 1
        counts[f"version_{info['version']}"] += 1
        counts[f"bone_type_{info['bone_type']}"] += 1
        try:
            mesh = parser0.parse(data)
            counts["parse_success"] += 1
            if mesh.vertex_count == 0 or mesh.face_count == 0:
                counts["empty_geometry"] += 1
        except Exception as exc:  # corpus audit must retain every unsupported variant
            counts["parse_failed"] += 1
            key = f"{type(exc).__name__}: {exc}"
            counts[f"error::{key}"] += 1
            failures.append(
                {
                    "path": str(path),
                    "bytes": len(data),
                    "sha256": digest,
                    "header": info,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
        if index % 1000 == 0:
            print(f"[audit] {index}/{len(paths)} unique={counts['unique_payloads']} failed={counts['parse_failed']}")

    report = {
        "schema_version": 1,
        "roots": [str(root.resolve()) for root in args.roots],
        "files_discovered": len(paths),
        "counts": dict(sorted(counts.items())),
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[summary] files={len(paths)} unique={counts['unique_payloads']} "
        f"success={counts['parse_success']} failed={counts['parse_failed']} duplicates={counts['duplicate_files']}"
    )
    return 0 if counts["parse_failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
