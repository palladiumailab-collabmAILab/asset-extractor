"""Convert one decoded NeoX mesh and one decoded texture payload to textured glTF.

The source files are read-only. The mesh and texture need not be an original pair;
use find_stage_asset_chain.py when logical path hashes permit a provenance match.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parent
SOURCE_TREE = TOOL_ROOT / "NeoXtractor-source-v3.2"
sys.path.insert(0, str(SOURCE_TREE))
sys.path.insert(0, str(TOOL_ROOT))

from core.images import convert_image  # noqa: E402
from core.mesh_converter.formats import gltf  # noqa: E402
from core.mesh_loader import MeshLoader  # noqa: E402
from convert_mesh_to_gltf import sanitize_skinning, sanitize_uvs  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mesh", type=Path)
    parser.add_argument("texture", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--provenance", choices=("matched", "technical-probe"), default="technical-probe")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    mesh = MeshLoader().load_from_file(args.mesh)
    if mesh is None:
        raise RuntimeError("MeshLoader returned no mesh")
    uv_result = sanitize_uvs(mesh)
    skin_result = sanitize_skinning(mesh)
    document = json.loads(gltf.convert(mesh).decode("utf-8"))

    extension = args.texture.suffix.lower().lstrip(".")
    image = convert_image(args.texture.read_bytes(), extension)
    if image is None:
        raise RuntimeError(f"Unsupported decoded texture extension: {extension}")
    png_name = args.texture.stem + ".png"
    png_path = args.output / png_name
    image.save(png_path, "PNG")

    document["images"] = [{"name": args.texture.stem, "uri": png_name}]
    document["samplers"] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]
    document["textures"] = [{"sampler": 0, "source": 0}]
    document["materials"] = [
        {
            "name": "NeoXTextureProbe",
            "doubleSided": True,
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": 0},
                "metallicFactor": 0.0,
                "roughnessFactor": 1.0,
            },
        }
    ]
    for gltf_mesh in document["meshes"]:
        for primitive in gltf_mesh["primitives"]:
            primitive["material"] = 0

    gltf_path = args.output / (args.mesh.stem + "_textured.gltf")
    gltf_path.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    report = {
        "mesh_source": str(args.mesh.resolve()),
        "texture_source": str(args.texture.resolve()),
        "source_pairing": args.provenance,
        "gltf": str(gltf_path.resolve()),
        "png": str(png_path.resolve()),
        "vertices": mesh.vertex_count,
        "faces": mesh.face_count,
        "uv": uv_result,
        "skinning": skin_result,
        "image_size": list(image.size),
        "image_mode": image.mode,
    }
    (args.output / "sample_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
