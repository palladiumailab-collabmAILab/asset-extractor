"""Import a .gltf/.glb passed by the Windows file association into Blender."""

from __future__ import annotations

import os
import sys

import bpy


def main() -> None:
    try:
        separator = sys.argv.index("--")
        paths = sys.argv[separator + 1 :]
    except ValueError:
        paths = sys.argv[1:]
    source = next((os.path.abspath(path) for path in paths if path.lower().endswith((".gltf", ".glb"))), None)
    if not source:
        raise RuntimeError("No .gltf or .glb path was supplied")
    if not os.path.isfile(source):
        raise FileNotFoundError(source)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=source)
    bpy.context.scene["ImportedGLTFSource"] = source


main()
