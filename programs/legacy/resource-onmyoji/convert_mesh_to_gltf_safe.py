"""Convert NeoX meshes to a Blender-importable glTF with safe joint remapping.

Some NeoX meshes contain sentinel/packed joint values outside the declared bone
array. The original decoded .mesh remains untouched. This bridge maps those
values to the mesh root joint and records the count so the result is valid glTF
for inspection; it does not claim to recover unknown game-specific bindings.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.mesh_converter.formats import gltf
from core.mesh_loader import MeshLoader


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    loader = MeshLoader()
    manifest: list[dict] = []

    for source in args.inputs:
        item = {"source": str(source), "status": "error"}
        try:
            mesh = loader.load_from_file(source)
            if mesh is None:
                raise RuntimeError("MeshLoader returned no mesh")
            root_index = next((i for i, parent in enumerate(mesh.bones.parents) if parent == -1), 0)
            bone_count = mesh.bones.count
            invalid = 0
            sanitized = []
            for row in mesh.bones.joints:
                fixed = []
                for joint in row:
                    if joint < 0 or joint >= bone_count or joint in (255, 65535):
                        invalid += 1
                        fixed.append(root_index)
                    else:
                        fixed.append(joint)
                sanitized.append(fixed)
            mesh.bones.joints = sanitized
            normalized_weights = []
            zero_weight_vertices = 0
            for row in mesh.bones.weights:
                values = [max(0.0, float(weight)) for weight in row]
                total = sum(values)
                if total <= 1e-8:
                    zero_weight_vertices += 1
                    normalized_weights.append([1.0, 0.0, 0.0, 0.0])
                else:
                    normalized_weights.append([value / total for value in values])
            mesh.bones.weights = normalized_weights
            payload = gltf.convert(mesh)
            target = args.output / f"{source.stem}.gltf"
            target.write_bytes(payload)
            item.update(
                {
                    "status": "ok",
                    "output": str(target),
                    "bytes": len(payload),
                    "vertex_count": mesh.vertex_count,
                    "face_count": mesh.face_count,
                    "uv_count": mesh.uv_count,
                    "has_bones": mesh.has_bones,
                    "bone_count": bone_count,
                    "root_joint_index": root_index,
                    "remapped_joint_values": invalid,
                    "zero_weight_vertices_fixed": zero_weight_vertices,
                }
            )
            print(f"[done] {source.name} -> {target.name} remapped_joints={invalid}")
        except Exception as exc:
            item["error"] = repr(exc)
            print(f"[error] {source}: {exc}")
        manifest.append(item)

    (args.output / "conversion_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0 if manifest and all(item["status"] == "ok" for item in manifest) else 2


if __name__ == "__main__":
    raise SystemExit(main())
