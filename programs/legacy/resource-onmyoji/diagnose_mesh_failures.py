"""Classify unsupported NeoX meshes using the parser's size metrics."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parent
SOURCE_TREE = TOOL_ROOT / "NeoXtractor-source-v3.2"
sys.path.insert(0, str(SOURCE_TREE))

import core.mesh_loader.parsers.new_parser as parser_module  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    audit = json.loads(args.audit.read_text(encoding="utf-8"))

    original_identify = parser_module.identify_mesh_type
    current: list[tuple] = []

    def capture(*values):
        current[:] = [values]
        return original_identify(*values)

    parser_module.identify_mesh_type = capture
    rows = []
    nearest_stride = Counter()
    exact_stride = Counter()
    for item in audit["failures"]:
        current.clear()
        path = Path(item["path"])
        try:
            parser_module.MeshParser0().parse(path.read_bytes())
        except Exception as exc:
            pass
        if not current:
            continue
        size, vertices, faces, split_bytes, uv_count, bone_type, version = current[-1]
        base = (
            size
            - split_bytes
            - (20 * vertices if bone_type in (1, 4) else 0)
            - 24 * vertices
            - 6 * faces
            - 8 * uv_count
            - 2
        )
        candidates = [(abs(base - stride * vertices), stride, base - stride * vertices) for stride in range(-32, 33)]
        _, stride, remainder = min(candidates)
        nearest_stride[(version, bone_type, stride, remainder)] += 1
        for exact in range(-32, 33):
            delta = base - exact * vertices
            if 0 <= delta <= 8 or delta == 32:
                exact_stride[(version, bone_type, exact, delta)] += 1
        rows.append(
            {
                "path": str(path),
                "version": version,
                "bone_type": bone_type,
                "mesh_data_size": size,
                "vertices": vertices,
                "faces": faces,
                "uv_count": uv_count,
                "base_residual": base,
                "nearest_extra_bytes_per_vertex": stride,
                "nearest_remainder": remainder,
            }
        )

    def counter_rows(counter: Counter) -> list[dict]:
        return [
            {
                "version": key[0],
                "bone_type": key[1],
                "extra_bytes_per_vertex": key[2],
                "remainder": key[3],
                "count": count,
            }
            for key, count in counter.most_common()
        ]

    report = {
        "source_audit": str(args.audit.resolve()),
        "captured_failure_count": len(rows),
        "exact_stride_patterns": counter_rows(exact_stride),
        "nearest_stride_patterns": counter_rows(nearest_stride),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["exact_stride_patterns"][:30], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
