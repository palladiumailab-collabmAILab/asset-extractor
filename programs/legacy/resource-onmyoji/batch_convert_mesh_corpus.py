"""Deduplicate and safely batch-convert extracted NeoX meshes to glTF.

Source files are read-only.  Each unique SHA-256 payload produces at most one
glTF, written atomically.  A manifest retains every duplicate source path.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parent
SOURCE_TREE = TOOL_ROOT / "NeoXtractor-source-v3.2"
sys.path[:0] = [str(SOURCE_TREE), str(TOOL_ROOT)]

from core.mesh_converter.formats import gltf  # noqa: E402
from core.mesh_loader import MeshLoader  # noqa: E402
from convert_mesh_to_gltf import sanitize_skinning, sanitize_uvs  # noqa: E402


def digest_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def validate_mesh(mesh) -> None:
    vertex_count = mesh.vertex_count
    if vertex_count <= 0 or mesh.face_count <= 0:
        raise ValueError("empty geometry")
    if len(mesh.mesh.position) != vertex_count or len(mesh.mesh.normal) != vertex_count:
        raise ValueError("vertex stream length mismatch")
    if any(index < 0 or index >= vertex_count for face in mesh.mesh.face for index in face):
        raise ValueError("face index outside vertex range")
    for stream_name, stream in (
        ("position", mesh.mesh.position),
        ("normal", mesh.mesh.normal),
        ("uv", mesh.mesh.uv),
    ):
        if any(not math.isfinite(float(value)) for row in stream for value in row):
            raise ValueError(f"non-finite {stream_name}")


def sanitize_uvs_or_drop(mesh) -> dict:
    """Keep valid UV blocks; drop undecodable streams for shape-only recovery."""
    try:
        return sanitize_uvs(mesh)
    except ValueError as exc:
        if not str(exc).startswith("UV count "):
            raise
        original_count = len(mesh.mesh.uv)
        mesh.mesh.uv = [(0.0, 0.0)] * mesh.vertex_count
        return {
            "status": "replaced_unaligned_stream_with_zero_uvs",
            "original_count": original_count,
            "final_count": mesh.vertex_count,
        }


def repair_nonfinite_normals(mesh) -> dict:
    normals = mesh.mesh.normal
    if len(normals) == mesh.vertex_count and all(
        math.isfinite(float(value)) for row in normals for value in row
    ):
        return {"status": "unchanged"}
    positions = mesh.mesh.position
    accumulated = [[0.0, 0.0, 0.0] for _ in positions]
    for a, b, c in mesh.mesh.face:
        pa, pb, pc = positions[a], positions[b], positions[c]
        ab = (pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2])
        ac = (pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2])
        cross = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        for index in (a, b, c):
            for axis in range(3):
                accumulated[index][axis] += cross[axis]
    repaired = []
    for x, y, z in accumulated:
        length = math.sqrt(x * x + y * y + z * z)
        repaired.append((x / length, y / length, z / length) if length > 1e-12 else (0.0, 0.0, 1.0))
    mesh.mesh.normal = repaired
    return {"status": "recomputed_from_faces"}


def convert_one(task: tuple[str, str, str, bool, bool]) -> dict:
    digest, source_text, output_text, colorize, resume = task
    source = Path(source_text)
    output = Path(output_text)
    if resume and output.is_file() and output.stat().st_size > 0:
        return {"sha256": digest, "source": source_text, "output": output_text, "status": "existing"}
    try:
        mesh = MeshLoader().load_from_file(source)
        if mesh is None:
            raise RuntimeError("MeshLoader returned no mesh")
        # Reject corrupt positions/indices before applying recoverable stream
        # repairs.  UVs are optional for the colorized shape-only corpus, and
        # normals can be reconstructed exactly from geometry.
        if any(not math.isfinite(float(value)) for row in mesh.mesh.position for value in row):
            raise ValueError("non-finite position")
        if any(index < 0 or index >= mesh.vertex_count for face in mesh.mesh.face for index in face):
            raise ValueError("face index outside vertex range")
        uv_result = sanitize_uvs_or_drop(mesh)
        skin_result = sanitize_skinning(mesh)
        normal_result = repair_nonfinite_normals(mesh)
        validate_mesh(mesh)
        payload = gltf.convert(mesh)
        document = json.loads(payload.decode("utf-8"))
        if not document.get("meshes") or not document.get("accessors"):
            raise ValueError("glTF has no mesh/accessor data")
        if colorize:
            rgb = [0.3 + int(digest[i : i + 2], 16) / 255.0 * 0.6 for i in (0, 2, 4)]
            document["materials"] = [{
                "name": "NeoXColorizedFallback",
                "doubleSided": True,
                "pbrMetallicRoughness": {
                    "baseColorFactor": [*rgb, 1.0],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.82,
                },
            }]
            for mesh_entry in document["meshes"]:
                for primitive in mesh_entry.get("primitives", []):
                    primitive["material"] = 0
            payload = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(output.name + f".tmp.{os.getpid()}")
        temporary.write_bytes(payload)
        temporary.replace(output)
        return {
            "sha256": digest,
            "source": source_text,
            "output": output_text,
            "status": "converted",
            "bytes": len(payload),
            "vertices": mesh.vertex_count,
            "faces": mesh.face_count,
            "mesh_type": mesh.type,
            "version": mesh.version,
            "uv_sanitization": uv_result,
            "skin_sanitization": skin_result,
            "normal_repair": normal_result,
        }
    except Exception as exc:
        return {
            "sha256": digest,
            "source": source_text,
            "output": None,
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=max(1, min(4, (os.cpu_count() or 2) // 2)))
    parser.add_argument("--limit", type=int, default=0, help="convert only the first N unique payloads")
    parser.add_argument("--colorize", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    gltf_dir = output / "gltf"
    paths = sorted(
        {path.resolve() for root in args.roots for path in root.resolve().rglob("*.mesh")},
        key=lambda path: str(path).lower(),
    )

    sources_by_digest: dict[str, list[str]] = defaultdict(list)
    sizes: dict[str, int] = {}
    representatives: dict[str, str] = {}
    for index, path in enumerate(paths, 1):
        digest, size = digest_file(path)
        sources_by_digest[digest].append(str(path))
        sizes[digest] = size
        representatives.setdefault(digest, str(path))
        if index % 2000 == 0:
            print(f"[hash] {index}/{len(paths)} unique={len(representatives)}")

    digests = sorted(representatives)
    if args.limit > 0:
        digests = digests[: args.limit]
    tasks = []
    for digest in digests:
        source = Path(representatives[digest])
        filename = f"{digest[:16]}__{source.stem}.gltf"
        tasks.append((digest, str(source), str(gltf_dir / filename), args.colorize, args.resume))

    results = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=max(1, args.workers)) as executor:
        for index, result in enumerate(executor.map(convert_one, tasks, chunksize=4), 1):
            results.append(result)
            if index % 250 == 0:
                failed = sum(item["status"] == "failed" for item in results)
                print(f"[convert] {index}/{len(tasks)} failed={failed}")

    manifest = {
        "schema_version": 1,
        "source_policy": "read-only",
        "roots": [str(root.resolve()) for root in args.roots],
        "files_discovered": len(paths),
        "unique_payloads_discovered": len(representatives),
        "unique_payloads_selected": len(tasks),
        "workers": max(1, args.workers),
        "colorized_fallback": args.colorize,
        "counts": {
            status: sum(item["status"] == status for item in results)
            for status in ("converted", "existing", "failed")
        },
        "assets": [
            {
                **result,
                "source_bytes": sizes[result["sha256"]],
                "duplicate_source_paths": sources_by_digest[result["sha256"]],
            }
            for result in results
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "batch_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    failures = [item for item in manifest["assets"] if item["status"] == "failed"]
    (output / "failures.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[summary] {manifest['counts']}")
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
