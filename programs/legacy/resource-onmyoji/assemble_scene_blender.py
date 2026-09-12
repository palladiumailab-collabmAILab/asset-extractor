"""Assemble a decoded SCN batch manifest into a colored Blender scene.

The source glTF files and the original APK extraction are read-only. Each
unique glTF is imported once, then linked object copies are placed using the
scene's recorded transform matrices. The manifest's NeoX Y-up coordinates are
converted to Blender's Z-up coordinates.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


def args_after_separator() -> list[str]:
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def safe_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", value) or "asset"


def neo_to_blender_matrix(values: list[float], scale: list[float]) -> Matrix:
    source = Matrix([values[index : index + 4] for index in range(0, 16, 4)])
    # NeoX scene coordinates are Y-up; Blender is Z-up.
    axis = Matrix(((1.0, 0.0, 0.0, 0.0), (0.0, 0.0, -1.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
    converted = axis @ source @ axis.inverted()
    converted.translation = axis @ source.translation
    converted = converted @ Matrix.Diagonal((scale[0], scale[1], scale[2], 1.0))
    return converted


def make_material(name: str, color: tuple[float, float, float, float]) -> bpy.types.Material:
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled:
        principled.inputs["Base Color"].default_value = color
        principled.inputs["Roughness"].default_value = 0.78
        principled.inputs["Metallic"].default_value = 0.0
    material.diffuse_color = color
    return material


def bounds_for(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    corners = [obj.matrix_world @ Vector(corner) for obj in objects if obj.type == "MESH" for corner in obj.bound_box]
    if not corners:
        return Vector((-1.0, -1.0, -1.0)), Vector((1.0, 1.0, 1.0))
    return Vector((min(p.x for p in corners), min(p.y for p in corners), min(p.z for p in corners))), Vector((max(p.x for p in corners), max(p.y for p in corners), max(p.z for p in corners)))


def look_at(obj: bpy.types.Object, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def main() -> int:
    args = args_after_separator()
    if len(args) < 2:
        raise SystemExit("usage: blender --background --python assemble_scene_blender.py -- batch_manifest.json output.blend [preview.png]")
    manifest_path = Path(args[0]).resolve()
    blend_path = Path(args[1]).resolve()
    preview_path = Path(args[2]).resolve() if len(args) > 2 else blend_path.with_name(blend_path.stem + "_preview.png")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "CENTIMETERS"
    scene.unit_settings.scale_length = 0.01
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 900
    scene.render.resolution_y = 650
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"

    root_collection = bpy.data.collections.new("OnmyojiStage")
    scene.collection.children.link(root_collection)
    assets_collection = bpy.data.collections.new("ImportedAssetInstances")
    root_collection.children.link(assets_collection)

    fallback = make_material("NeoXColorizedFallback_Assembled", (0.58, 0.18, 0.08, 1.0))
    created_objects: list[bpy.types.Object] = []
    converted_assets = 0
    placed_instances = 0
    skipped_assets = []

    for asset in manifest.get("assets", []):
        conversion = asset.get("conversion") or {}
        output = conversion.get("output")
        instances = asset.get("instances") or []
        if not output or not Path(output).is_file() or not instances:
            skipped_assets.append(asset.get("logical_gim", ""))
            continue
        before = set(bpy.data.objects)
        result = bpy.ops.import_scene.gltf(filepath=str(Path(output).resolve()))
        if "FINISHED" not in result:
            skipped_assets.append(asset.get("logical_gim", ""))
            continue
        imported = [obj for obj in bpy.data.objects if obj not in before]
        templates = [(obj.matrix_world.copy(), obj.type, obj.data) for obj in imported]
        if not templates:
            skipped_assets.append(asset.get("logical_gim", ""))
            continue
        for obj in imported:
            for collection in list(obj.users_collection):
                collection.objects.unlink(obj)
            bpy.data.objects.remove(obj, do_unlink=True)

        converted_assets += 1
        for instance in instances:
            root = bpy.data.objects.new(safe_name(instance.get("name", "Instance")), None)
            assets_collection.objects.link(root)
            root["LogicalGIM"] = asset.get("logical_gim", "")
            root["UUID"] = instance.get("uuid", "")
            root.matrix_world = neo_to_blender_matrix(instance["rotation_matrix"], instance["scale"])
            root.matrix_world.translation = Vector((instance["position"][0], instance["position"][2], -instance["position"][1]))
            for local_matrix, object_type, data in templates:
                duplicate = bpy.data.objects.new(f"{root.name}_{object_type}", data)
                assets_collection.objects.link(duplicate)
                duplicate.parent = root
                duplicate.matrix_parent_inverse = Matrix.Identity(4)
                duplicate.matrix_basis = local_matrix
                if duplicate.type == "MESH" and len(duplicate.data.materials) == 0:
                    duplicate.data.materials.append(fallback)
                created_objects.append(duplicate)
            placed_instances += 1

    min_v, max_v = bounds_for(created_objects)
    center = (min_v + max_v) * 0.5
    radius = max((max_v - min_v).length * 0.5, 100.0)

    ground = bpy.data.meshes.new("PreviewGroundMesh")
    ground.from_pydata([(min_v.x - radius, min_v.y - radius, min_v.z - 2.0), (max_v.x + radius, min_v.y - radius, min_v.z - 2.0), (max_v.x + radius, max_v.y + radius, min_v.z - 2.0), (min_v.x - radius, max_v.y + radius, min_v.z - 2.0)], [], [(0, 1, 2, 3)])
    ground.update()
    ground_object = bpy.data.objects.new("PreviewGround", ground)
    assets_collection.objects.link(ground_object)
    ground_object.data.materials.append(make_material("PreviewGroundMaterial", (0.035, 0.055, 0.075, 1.0)))

    camera_data = bpy.data.cameras.new("StagePreviewCamera")
    camera = bpy.data.objects.new("StagePreviewCamera", camera_data)
    assets_collection.objects.link(camera)
    camera.location = center + Vector((radius * 1.15, -radius * 1.15, radius * 0.82))
    camera_data.lens = 48
    # The recovered scene uses a large source-space coordinate range.  The
    # Blender default far clip (1 km) would leave the preview blank, so size
    # the frustum from the assembled bounds.
    camera_data.clip_start = max(radius * 0.00001, 0.01)
    camera_data.clip_end = max(radius * 8.0, 1000.0)
    look_at(camera, center)
    scene.camera = camera

    sun_data = bpy.data.lights.new("StageSun", type="SUN")
    sun_data.energy = 2.2
    sun = bpy.data.objects.new("StageSun", sun_data)
    assets_collection.objects.link(sun)
    sun.rotation_euler = (math.radians(28), math.radians(-25), math.radians(32))
    area_data = bpy.data.lights.new("StageFill", type="AREA")
    area_data.energy = 1800
    area_data.shape = "DISK"
    area_data.size = radius * 0.75
    area = bpy.data.objects.new("StageFill", area_data)
    assets_collection.objects.link(area)
    area.location = center + Vector((-radius * 0.55, -radius * 0.35, radius * 1.2))
    look_at(area, center)
    scene.world = scene.world or bpy.data.worlds.new("StageWorld")
    scene.world.color = (0.025, 0.035, 0.06)
    scene.view_settings.exposure = 1.0
    scene.render.filepath = str(preview_path)
    blend_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    report = {
        "manifest": str(manifest_path),
        "blend": str(blend_path),
        "preview": str(preview_path),
        "converted_asset_templates": converted_assets,
        "placed_instances": placed_instances,
        "created_objects": len(created_objects),
        "skipped_assets": skipped_assets,
        "bounds_min": list(min_v),
        "bounds_max": list(max_v),
        "material_mode": "existing glTF colorized fallback plus assembled fallback",
        "source_policy": "read-only",
    }
    blend_path.with_name(blend_path.stem + "_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
