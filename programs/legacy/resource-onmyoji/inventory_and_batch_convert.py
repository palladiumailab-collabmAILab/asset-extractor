"""Inventory every decoded NeoX mesh and batch-convert supported unique assets.

The input tree is read-only. Files are deduplicated by content hash, each unique
mesh is probed through the repaired MeshLoader, and supported meshes are emitted
as glTF under the output directory. A manifest maps every original file to its
classification and, when possible, its reusable glTF output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

TOOL_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = TOOL_ROOT / "NeoXtractor-source-v3.2"
sys.path.insert(0, str(SOURCE_ROOT))
sys.path.insert(0, str(TOOL_ROOT))

from core.mesh_converter.formats import gltf  # noqa: E402
from core.mesh_loader import MeshLoader  # noqa: E402
from convert_mesh_to_gltf import sanitize_skinning, sanitize_uvs  # noqa: E402


def safe_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", value) or "mesh"


def digest_file(path: Path) -> tuple[str, str, int]:
    hasher = hashlib.blake2b(digest_size=16)
    size = 0
    with path.open("rb") as handle:
        header = handle.read(32)
        size += len(header)
        hasher.update(header)
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            hasher.update(chunk)
    return hasher.hexdigest(), header.hex(), size


def color_for(key: str) -> list[float]:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return [0.28 + digest[0] / 255.0 * 0.62, 0.28 + digest[1] / 255.0 * 0.62, 0.28 + digest[2] / 255.0 * 0.62, 1.0]


def convert_one(item: dict[str, Any], output_dir: Path, colorize: bool) -> dict[str, Any]:
    source = Path(item["representative"])
    result: dict[str, Any] = {
        "content_hash": item["content_hash"],
        "representative": str(source),
        "all_sources": item["sources"],
        "size": item["size"],
        "header_hex": item["header_hex"],
    }
    try:
        mesh = MeshLoader().load_from_file(source)
        if mesh is None:
            raise RuntimeError("MeshLoader returned no mesh")
        uv_fix = sanitize_uvs(mesh)
        skin_fix = sanitize_skinning(mesh)
        payload = gltf.convert(mesh)
        if colorize:
            document = json.loads(payload.decode("utf-8"))
            document["materials"] = [{
                "name": "NeoXColorizedFallback",
                "doubleSided": True,
                "pbrMetallicRoughness": {
                    "baseColorFactor": color_for(item["content_hash"]),
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.82,
                },
            }]
            for mesh_entry in document.get("meshes", []):
                for primitive in mesh_entry.get("primitives", []):
                    primitive["material"] = 0
            payload = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        out_name = f"{safe_name(source.stem)}_{item['content_hash']}.gltf"
        target = output_dir / "gltf" / out_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        result.update({
            "status": "convertible",
            "output": str(target),
            "bytes": len(payload),
            "vertex_count": mesh.vertex_count,
            "face_count": mesh.face_count,
            "uv_count": mesh.uv_count,
            "has_bones": mesh.has_bones,
            "bone_count": mesh.bones.count if mesh.has_bones else 0,
            "mesh_type": getattr(mesh, "type", None),
            "uv_sanitization": uv_fix,
            "skin_sanitization": skin_fix,
            "material_mode": "presentation_colorized_fallback" if colorize else "shape_only_default_glTF_material",
        })
    except Exception as exc:  # noqa: BLE001 - inventory must classify every file
        result.update({"status": "unconvertible", "error": f"{type(exc).__name__}: {exc}"})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extracted", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=max(1, min(4, (os.cpu_count() or 2))))
    parser.add_argument("--colorize", action="store_true")
    parser.add_argument("--no-convert", action="store_true", help="inventory only")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    root = args.extracted.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    files = sorted(root.rglob("*.mesh"), key=lambda path: str(path).lower())
    grouped: dict[str, dict[str, Any]] = {}
    for index, path in enumerate(files, 1):
        digest, header, size = digest_file(path)
        entry = grouped.setdefault(digest, {"content_hash": digest, "representative": str(path), "sources": [], "size": size, "header_hex": header})
        entry["sources"].append(str(path))
        if index % 5000 == 0:
            print(f"hashed {index}/{len(files)}", flush=True)

    items = list(grouped.values())
    results: list[dict[str, Any]] = []
    if args.no_convert:
        results = [{**item, "status": "not_probed"} for item in items]
    else:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = [pool.submit(convert_one, item, output, args.colorize) for item in items]
            for index, future in enumerate(as_completed(futures), 1):
                results.append(future.result())
                if index % 500 == 0:
                    print(f"processed {index}/{len(items)}", flush=True)
    results.sort(key=lambda record: record["content_hash"])
    convertible = sum(record["status"] == "convertible" for record in results)
    unconvertible = sum(record["status"] == "unconvertible" for record in results)
    manifest = {
        "schema_version": 1,
        "source_root": str(root),
        "source_mesh_count": len(files),
        "unique_content_count": len(items),
        "duplicate_mesh_count": len(files) - len(items),
        "convertible_unique_count": convertible,
        "unconvertible_unique_count": unconvertible,
        "colorized": bool(args.colorize),
        "classification": "convertible means MeshLoader + glTF conversion succeeded; unconvertible contains the exception and representative data",
        "assets": results,
    }
    (output / "mesh_inventory.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {key: manifest[key] for key in ("source_mesh_count", "unique_content_count", "duplicate_mesh_count", "convertible_unique_count", "unconvertible_unique_count")}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if unconvertible == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
