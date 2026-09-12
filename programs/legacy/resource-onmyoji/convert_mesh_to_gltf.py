"""Convert decoded NeoX .mesh files to embedded glTF 2.0.

The input mesh is never changed. This is a small reproducible bridge from the
NeoXtractor MeshLoader to Blender/Unreal-friendly glTF output.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from core.mesh_converter.formats import gltf
from core.mesh_loader import MeshLoader


def sanitize_uvs(mesh) -> dict:
    """Keep a glTF-valid UV0 stream when NeoX reports trailing UV data.

    The bundled converter writes the complete ``mesh.uv`` list as TEXCOORD_0.
    Some static NeoX meshes expose two or four vertex-sized blocks there; glTF
    requires every primitive vertex attribute to have the POSITION count.  The
    first block has the expected normalized UV range in the affected samples,
    while later blocks contain padding or game-specific data.  Preserve the
    decoded source and record any compatibility truncation in the manifest.
    """
    vertex_count = mesh.vertex_count
    uv_count = len(mesh.mesh.uv)
    if uv_count == vertex_count:
        return {"applied": False, "input_uv_count": uv_count, "output_uv_count": uv_count}
    if uv_count < vertex_count or uv_count % vertex_count:
        raise ValueError(
            f"UV count {uv_count} is not a whole number of vertex-sized blocks ({vertex_count})"
        )
    blocks = uv_count // vertex_count
    mesh.mesh.uv = mesh.mesh.uv[:vertex_count]
    return {
        "applied": True,
        "input_uv_count": uv_count,
        "output_uv_count": vertex_count,
        "input_blocks": blocks,
        "discarded_uv_values": uv_count - vertex_count,
        "policy": "keep_first_vertex_sized_block_as_texcoord_0",
    }


def sanitize_skinning(mesh) -> dict:
    """Make NeoX skin influences valid for glTF without changing the source file.

    glTF JOINTS_0 values index the skin.joints array, so every weighted joint must
    be in ``[0, bone_count)``. Some NeoX meshes contain sentinel or palette values
    outside that range. Drop those influences, normalize the remaining weights,
    and bind otherwise unweighted vertices to the skeleton root.
    """
    if not mesh.has_bones:
        return {"applied": False}

    bone_count = mesh.bones.count
    if bone_count <= 0:
        raise ValueError("Mesh reports skinning but has no bones")
    if (
        len(mesh.bones.joints) != mesh.vertex_count
        or len(mesh.bones.weights) != mesh.vertex_count
    ):
        raise ValueError("Skin influence count does not match the vertex count")

    try:
        root_joint = mesh.bones.parents.index(-1)
    except ValueError:
        root_joint = 0

    invalid_slots = 0
    invalid_weighted_slots = 0
    renormalized_vertices = 0
    root_bound_vertices = 0
    max_input_joint = 0
    clean_joints = []
    clean_weights = []

    for joints, weights in zip(mesh.bones.joints, mesh.bones.weights):
        if len(joints) != 4 or len(weights) != 4:
            raise ValueError("glTF export requires exactly four influences per vertex")
        output_joints = []
        output_weights = []
        for joint, weight in zip(joints, weights):
            joint = int(joint)
            weight = float(weight)
            max_input_joint = max(max_input_joint, joint)
            valid_weight = weight if math.isfinite(weight) and weight > 0.0 else 0.0
            if not 0 <= joint < bone_count:
                invalid_slots += 1
                if valid_weight > 0.0:
                    invalid_weighted_slots += 1
                output_joints.append(root_joint)
                output_weights.append(0.0)
            else:
                output_joints.append(joint)
                output_weights.append(valid_weight)

        total = sum(output_weights)
        if total > 0.0:
            if not math.isclose(total, 1.0, rel_tol=1e-6, abs_tol=1e-6):
                renormalized_vertices += 1
            output_weights = [weight / total for weight in output_weights]
        else:
            output_joints = [root_joint, root_joint, root_joint, root_joint]
            output_weights = [1.0, 0.0, 0.0, 0.0]
            root_bound_vertices += 1

        clean_joints.append(tuple(output_joints))
        clean_weights.append(tuple(output_weights))

    mesh.bones.joints = clean_joints
    mesh.bones.weights = clean_weights
    return {
        "applied": True,
        "root_joint": root_joint,
        "max_input_joint": max_input_joint,
        "max_output_joint": max(max(joints) for joints in clean_joints),
        "invalid_slots": invalid_slots,
        "invalid_weighted_slots": invalid_weighted_slots,
        "renormalized_vertices": renormalized_vertices,
        "root_bound_vertices": root_bound_vertices,
    }


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
            uv_sanitization = sanitize_uvs(mesh)
            skin_sanitization = sanitize_skinning(mesh)
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
                    "bone_count": mesh.bones.count if mesh.has_bones else 0,
                    "uv_sanitization": uv_sanitization,
                    "skin_sanitization": skin_sanitization,
                }
            )
            print(f"[done] {source.name} -> {target.name} vertices={mesh.vertex_count} faces={mesh.face_count}")
        except Exception as exc:  # keep batch conversions reproducible
            item["error"] = repr(exc)
            print(f"[error] {source}: {exc}")
        manifest.append(item)

    (args.output / "conversion_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0 if manifest and all(item["status"] == "ok" for item in manifest) else 2


if __name__ == "__main__":
    raise SystemExit(main())
