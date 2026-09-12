import json
import sys
from pathlib import Path

import bpy


def main() -> int:
    if len(sys.argv) < 3:
        raise SystemExit("usage: blender --background --python blender_validate_gltf.py -- input.gltf output.blend")
    source = Path(sys.argv[-2]).resolve()
    target = Path(sys.argv[-1]).resolve()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    result = bpy.ops.import_scene.gltf(filepath=str(source))
    if "FINISHED" not in result:
        raise RuntimeError(f"glTF import failed: {result}")
    objects = [obj for obj in bpy.context.scene.objects]
    meshes = [obj for obj in objects if obj.type == "MESH"]
    armatures = [obj for obj in objects if obj.type == "ARMATURE"]
    materials = [mat for mat in bpy.data.materials]
    target.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(target))
    report = {
        "source": str(source),
        "blend": str(target),
        "objects": len(objects),
        "meshes": len(meshes),
        "armatures": len(armatures),
        "materials": len(materials),
    }
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
