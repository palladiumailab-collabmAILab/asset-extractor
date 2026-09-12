"""Import a textured glTF in Blender, render a quick proof, and save a .blend."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def main():
    if "--" not in sys.argv or len(sys.argv) < sys.argv.index("--") + 3:
        raise SystemExit("usage: blender --background --python blender_validate_textured_gltf.py -- input.gltf output.blend")
    args = sys.argv[sys.argv.index("--") + 1 :]
    source = Path(args[0]).resolve()
    blend_path = Path(args[1]).resolve()
    render_path = blend_path.with_name(blend_path.stem + "_render.png")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    result = bpy.ops.import_scene.gltf(filepath=str(source))
    if "FINISHED" not in result:
        raise RuntimeError(f"glTF import failed: {result}")
    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not mesh_objects:
        raise RuntimeError("No mesh imported")
    original_materials = [mat.name for mat in bpy.data.materials]
    color_mat = bpy.data.materials.new("NeoXColorizedFallback")
    color_mat.use_nodes = True
    nodes = color_mat.node_tree.nodes
    principled = nodes.get("Principled BSDF")
    if principled:
        principled.inputs["Base Color"].default_value = (0.30, 0.035, 0.018, 1.0)
        principled.inputs["Roughness"].default_value = 0.52
        principled.inputs["Metallic"].default_value = 0.08
    for obj in mesh_objects:
        obj.data.materials.append(color_mat)
        for index in range(len(obj.data.materials) - 1):
            obj.data.materials[index] = color_mat
    points = [obj.matrix_world @ Vector(corner) for obj in mesh_objects for corner in obj.bound_box]
    min_v = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    max_v = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    center = (min_v + max_v) * 0.5
    radius = max((max_v - min_v).length * 0.5, 1.0)

    camera_data = bpy.data.cameras.new("ProbeCamera")
    camera = bpy.data.objects.new("ProbeCamera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = center + Vector((radius * 2.4, -radius * 2.4, radius * 1.8))
    camera_data.lens = 52
    look_at(camera, center)
    bpy.context.scene.camera = camera

    light_data = bpy.data.lights.new("ProbeKey", type="AREA")
    light_data.energy = 4000
    light_data.shape = "DISK"
    light_data.size = radius * 2.0
    light = bpy.data.objects.new("ProbeKey", light_data)
    bpy.context.collection.objects.link(light)
    light.location = center + Vector((radius, -radius, radius * 2.0))
    look_at(light, center)

    fill_data = bpy.data.lights.new("ProbeFill", type="AREA")
    fill_data.energy = 2200
    fill_data.size = radius
    fill = bpy.data.objects.new("ProbeFill", fill_data)
    bpy.context.collection.objects.link(fill)
    fill.location = center + Vector((-radius, -radius, radius))
    look_at(fill, center)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(render_path)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("ProbeWorld")
    scene.world.color = (0.12, 0.14, 0.20)
    scene.view_settings.exposure = 2.0
    bpy.ops.render.render(write_still=True)
    blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    report = {
        "source": str(source),
        "blend": str(blend_path),
        "render": str(render_path),
        "objects": len(bpy.context.scene.objects),
        "meshes": len(mesh_objects),
        "materials": len(bpy.data.materials),
        "images": len(bpy.data.images),
        "material_names": [mat.name for mat in bpy.data.materials],
        "original_material_names": original_materials,
        "presentation_material": "NeoXColorizedFallback",
        "image_names": [image.name for image in bpy.data.images],
        "bounds": {"min": list(min_v), "max": list(max_v)},
    }
    report_path = blend_path.with_name(blend_path.stem + "_report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
