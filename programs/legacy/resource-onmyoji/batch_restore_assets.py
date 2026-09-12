"""Restore scene-referenced NeoX assets into Blender/UE-friendly glTF/PNG.

The source tree is read only.  The deterministic rule currently proven for the
captured ExtraRes tree is the low 32-bit suffix of ``mesh_hash(logical_path)``:

    scene .gim -> replace .gim with .mesh -> hashed decoded .mesh

The scene's transforms are retained in ``batch_manifest.json``.  A mesh can be
converted to shape-only glTF even when the original MTL/texture relationship
cannot be proven.  Material guesses are never applied; they are reported in
``unresolved.json`` instead.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Iterable

TOOL_ROOT = Path(__file__).resolve().parent
SOURCE_TREE = TOOL_ROOT / "NeoXtractor-source-v3.2"
sys.path.insert(0, str(SOURCE_TREE))
sys.path.insert(0, str(TOOL_ROOT))

from core.images import convert_image  # noqa: E402
from core.mesh_converter.formats import gltf  # noqa: E402
from core.mesh_loader import MeshLoader  # noqa: E402
from convert_mesh_to_gltf import sanitize_skinning, sanitize_uvs  # noqa: E402
from core.npk.npkhash_v1 import mesh_hash  # noqa: E402


HASH_RE = re.compile(r"([0-9a-fA-F]{8})$")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tga", ".bmp", ".dds", ".ktx", ".pvr", ".astc"}
LOGICAL_IMAGE_RE = re.compile(
    r"(?i)(?:Value\s*=\s*|value\s*=\s*)[\"']([^\"']+\.(?:png|jpg|jpeg|tga|bmp|dds|ktx|pvr|astc))[\"']"
)


def normalized(path: str) -> str:
    return path.replace("/", "\\").lower()


def hash_key(path: str) -> str:
    return f"{mesh_hash(normalized(path)):08x}"


def safe_name(path: str) -> str:
    stem = Path(path.replace("\\", "/")).stem
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", stem) or "asset"


def parse_float_vector(value: str | None) -> list[float] | None:
    if not value:
        return None
    try:
        return [float(part) for part in value.split(",")]
    except ValueError:
        return None


def build_hash_index(extracted_root: Path) -> dict[str, list[Path]]:
    by_hash: dict[str, list[Path]] = defaultdict(list)
    for path in extracted_root.rglob("*"):
        if not path.is_file():
            continue
        match = HASH_RE.search(path.stem)
        if match:
            by_hash[match.group(1).lower()].append(path)
    for paths in by_hash.values():
        paths.sort(key=lambda value: str(value).lower())
    return dict(by_hash)


def resolve_hashed(
    by_hash: dict[str, list[Path]], logical_path: str, extensions: set[str] | None = None
) -> list[Path]:
    candidates = by_hash.get(hash_key(logical_path), [])
    if extensions is None:
        return list(candidates)
    return [path for path in candidates if path.suffix.lower() in extensions]


def parse_scene(scene_path: Path) -> tuple[list[str], list[dict]]:
    root = ET.parse(scene_path).getroot()
    all_files_element = next((node for node in root.iter() if node.tag == "AllFiles"), None)
    file_paths: list[str] = []
    if all_files_element is not None:
        for child in list(all_files_element):
            path = child.attrib.get("Path", "")
            file_paths.append(path)

    models_element = next((node for node in root.iter() if node.tag == "Models"), None)
    instances: list[dict] = []
    if models_element is not None:
        for index, model in enumerate(list(models_element)):
            if model.tag.lower() != "model":
                continue
            raw_index = model.attrib.get("FilePathIndex", "-1")
            try:
                file_index = int(raw_index)
            except ValueError:
                file_index = -1
            logical_gim = file_paths[file_index] if 0 <= file_index < len(file_paths) else None
            instances.append(
                {
                    "instance_index": index,
                    "file_path_index": file_index,
                    "logical_gim": logical_gim,
                    "name": model.attrib.get("Name", ""),
                    "uuid": model.attrib.get("UUID", ""),
                    "position": parse_float_vector(model.attrib.get("Position")),
                    "rotation_matrix": parse_float_vector(model.attrib.get("Rotation")),
                    "scale": parse_float_vector(model.attrib.get("Scale")),
                }
            )
    return file_paths, instances


def read_gim_info(path: Path | None) -> dict:
    if path is None:
        return {"submeshes": [], "references": []}
    text = path.read_text(encoding="utf-8", errors="ignore")
    try:
        root = ET.fromstring(text)
        submeshes = []
        for node in root.iter():
            if node.tag.lower().startswith("sub") and node.attrib.get("Name"):
                submeshes.append(
                    {
                        "name": node.attrib.get("Name"),
                        "mtl_index": node.attrib.get("MtlIdx"),
                    }
                )
    except ET.ParseError:
        submeshes = []
    refs = re.findall(r"(?i)(?:Mesh|FileName|Value)\s*=\s*[\"']([^\"']+)[\"']", text)
    return {"submeshes": submeshes, "references": refs}


def material_candidates(
    by_hash: dict[str, list[Path]], logical_gim: str, gim_path: Path | None
) -> tuple[list[Path], list[str]]:
    """Return only MTL candidates supported by an explicit path/reference."""
    base = logical_gim[:-4] if logical_gim.lower().endswith(".gim") else logical_gim
    candidates: list[Path] = []
    reasons: list[str] = []
    for logical in (base + ".mtl", base + ".material"):
        candidates.extend(resolve_hashed(by_hash, logical, {".mtl"}))
    if gim_path is not None:
        text = gim_path.read_text(encoding="utf-8", errors="ignore")
        refs = re.findall(r"(?i)[\"']([^\"']+\.mtl)[\"']", text)
        for ref in refs:
            candidates.extend(resolve_hashed(by_hash, ref, {".mtl"}))
    unique = sorted({path.resolve() for path in candidates}, key=lambda value: str(value).lower())
    if not unique:
        reasons.append("no_explicit_mtl_path_or_hash_match")
    elif len(unique) > 1:
        reasons.append("multiple_mtl_candidates")
    return unique, reasons


def texture_candidates(by_hash: dict[str, list[Path]], logical_ref: str) -> list[Path]:
    """Resolve texture hashes while allowing the decoded container extension."""
    ref = logical_ref.replace("/", "\\")
    stem = ref.rsplit(".", 1)[0] if "." in ref.rsplit("\\", 1)[-1] else ref
    logical_variants = [ref]
    for extension in ("png", "jpg", "jpeg", "tga", "ktx", "pvr", "astc", "dds", "bmp"):
        logical_variants.append(stem + "." + extension)
    found: set[Path] = set()
    for variant in logical_variants:
        found.update(resolve_hashed(by_hash, variant, IMAGE_EXTENSIONS))
    return sorted(found, key=lambda value: str(value).lower())


def parse_mtl(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return sorted(set(LOGICAL_IMAGE_RE.findall(text)), key=str.lower)


def decode_texture(source: Path, target: Path) -> dict:
    extension = source.suffix.lower().lstrip(".")
    image = convert_image(source.read_bytes(), extension)
    if image is None:
        raise RuntimeError(f"unsupported image payload: {source.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "PNG")
    return {"source": str(source.resolve()), "output": str(target.resolve()), "size": list(image.size)}


def presentation_color(key: str) -> list[float]:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return [0.28 + digest[0] / 255.0 * 0.62, 0.28 + digest[1] / 255.0 * 0.62, 0.28 + digest[2] / 255.0 * 0.62, 1.0]


def convert_mesh(source: Path, target: Path, colorize: bool = False) -> dict:
    mesh = MeshLoader().load_from_file(source)
    if mesh is None:
        raise RuntimeError("MeshLoader returned no mesh")
    uv_result = sanitize_uvs(mesh)
    skin_result = sanitize_skinning(mesh)
    payload = gltf.convert(mesh)
    if colorize:
        document = json.loads(payload.decode("utf-8"))
        document["materials"] = [{
            "name": "NeoXColorizedFallback",
            "doubleSided": True,
            "pbrMetallicRoughness": {
                "baseColorFactor": presentation_color(source.stem),
                "metallicFactor": 0.0,
                "roughnessFactor": 0.82,
            },
        }]
        for mesh_entry in document.get("meshes", []):
            for primitive in mesh_entry.get("primitives", []):
                primitive["material"] = 0
        payload = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return {
        "output": str(target.resolve()),
        "bytes": len(payload),
        "vertex_count": mesh.vertex_count,
        "face_count": mesh.face_count,
        "uv_count": mesh.uv_count,
        "has_bones": mesh.has_bones,
        "bone_count": mesh.bones.count if mesh.has_bones else 0,
        "uv_sanitization": uv_result,
        "skin_sanitization": skin_result,
        "material_mode": "presentation_colorized_fallback" if colorize else "shape_only_default_glTF_material",
    }


def iter_unique(values: Iterable[Path]) -> list[Path]:
    return list(dict.fromkeys(path.resolve() for path in values))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extracted", type=Path, help="decoded extraction root containing res/")
    parser.add_argument("--scene", type=Path, help="scene .scn; defaults to the first scene")
    parser.add_argument("--output", type=Path, help="output root; defaults to converted/batch_restore/<scene>")
    parser.add_argument("--limit", type=int, default=12, help="maximum unique scene meshes (default: 12)")
    parser.add_argument("--all", action="store_true", help="convert every uniquely resolved scene mesh")
    parser.add_argument("--colorize", action="store_true", help="attach a deterministic presentation-only fallback color")
    parser.add_argument("--no-textures", dest="decode_textures", action="store_false", help="skip proven MTL texture decode")
    parser.set_defaults(decode_textures=True)
    args = parser.parse_args()

    extracted = args.extracted.resolve()
    scenes = [args.scene.resolve()] if args.scene else sorted(extracted.rglob("*.scn"))
    if not scenes:
        raise SystemExit("No .scn scene found")
    scene = scenes[0]
    output = (args.output or (extracted.parent.parent / "converted" / "batch_restore" / safe_name(scene.name))).resolve()
    output.mkdir(parents=True, exist_ok=True)
    gltf_dir = output / "gltf"
    texture_dir = output / "textures"
    log_path = output / "conversion.log"
    log_lines: list[str] = []

    def log(message: str) -> None:
        print(message)
        log_lines.append(message)

    log(f"[index] extracted={extracted}")
    by_hash = build_hash_index(extracted)
    file_paths, instances = parse_scene(scene)
    scene_gims = [path for path in file_paths if path.lower().endswith(".gim")]
    unique_gims = list(dict.fromkeys(scene_gims))
    if args.all:
        selected_gims = unique_gims
    else:
        selected_gims = unique_gims[: max(0, args.limit)]
    instance_by_gim: dict[str, list[dict]] = defaultdict(list)
    for instance in instances:
        if instance.get("logical_gim"):
            instance_by_gim[instance["logical_gim"]].append(instance)

    assets: list[dict] = []
    unresolved: list[dict] = []
    converted_count = 0
    texture_count = 0
    for asset_index, logical_gim in enumerate(selected_gims):
        base = logical_gim[:-4]
        mesh_logical = base + ".mesh"
        gim_paths = resolve_hashed(by_hash, logical_gim, {".gim"})
        mesh_paths = resolve_hashed(by_hash, mesh_logical, {".mesh"})
        asset = {
            "asset_index": asset_index,
            "logical_gim": logical_gim,
            "logical_mesh": mesh_logical,
            "instances": instance_by_gim.get(logical_gim, []),
            "instance_count": len(instance_by_gim.get(logical_gim, [])),
            "gim_candidates": [str(path.resolve()) for path in gim_paths],
            "mesh_candidates": [str(path.resolve()) for path in mesh_paths],
            "status": "unresolved",
            "unresolved_reasons": [],
            "material_status": "unresolved",
        }
        gim_path = gim_paths[0] if len(gim_paths) == 1 else None
        if not gim_paths:
            asset["unresolved_reasons"].append("gim_hash_not_found")
        elif len(gim_paths) > 1:
            asset["unresolved_reasons"].append("gim_hash_ambiguous")
        asset["gim_info"] = read_gim_info(gim_path)
        if not mesh_paths:
            asset["unresolved_reasons"].append("mesh_hash_not_found")
        elif len(mesh_paths) > 1:
            asset["unresolved_reasons"].append("mesh_hash_ambiguous")
        mesh_path = mesh_paths[0] if len(mesh_paths) == 1 else None
        mtl_paths, mtl_reasons = material_candidates(by_hash, logical_gim, gim_path)
        asset["mtl_candidates"] = [str(path.resolve()) for path in mtl_paths]
        asset["unresolved_reasons"].extend(mtl_reasons)
        if len(mtl_paths) == 1:
            asset["material_status"] = "explicit_mtl_path_resolved"
            texture_records = []
            for logical_ref in parse_mtl(mtl_paths[0]):
                candidates = texture_candidates(by_hash, logical_ref)
                if len(candidates) != 1:
                    asset["unresolved_reasons"].append(
                        f"texture_unresolved:{logical_ref}:{len(candidates)}_candidates"
                    )
                    continue
                source = candidates[0]
                if args.decode_textures:
                    texture_target = texture_dir / f"{asset_index:04d}_{safe_name(source.name)}.png"
                    try:
                        record = decode_texture(source, texture_target)
                        record["logical_reference"] = logical_ref
                        texture_records.append(record)
                        texture_count += 1
                    except Exception as exc:
                        asset["unresolved_reasons"].append(f"texture_decode_failed:{logical_ref}:{exc}")
                else:
                    texture_records.append({"logical_reference": logical_ref, "source": str(source.resolve())})
            asset["textures"] = texture_records
        else:
            asset["textures"] = []
        if mesh_path is not None:
            target = gltf_dir / f"{asset_index:04d}_{safe_name(logical_gim)}_{hash_key(mesh_logical)}.gltf"
            try:
                asset["conversion"] = convert_mesh(mesh_path, target, colorize=args.colorize)
                asset["status"] = "converted_shape_only"
                converted_count += 1
                log(f"[mesh {asset_index + 1}/{len(selected_gims)}] OK {logical_gim} -> {target.name}")
            except Exception as exc:
                asset["unresolved_reasons"].append(f"mesh_conversion_failed:{exc}")
                log(f"[mesh {asset_index + 1}/{len(selected_gims)}] ERROR {logical_gim}: {exc}")
        else:
            log(f"[mesh {asset_index + 1}/{len(selected_gims)}] UNRESOLVED {logical_gim}")
        if asset["unresolved_reasons"]:
            unresolved.append(
                {
                    "asset_index": asset_index,
                    "logical_gim": logical_gim,
                    "logical_mesh": mesh_logical,
                    "reasons": sorted(set(asset["unresolved_reasons"])),
                    "material_status": asset["material_status"],
                    "gim_candidates": asset["gim_candidates"],
                    "mesh_candidates": asset["mesh_candidates"],
                    "mtl_candidates": asset["mtl_candidates"],
                }
            )
        assets.append(asset)

    manifest = {
        "schema_version": 1,
        "source_extracted_root": str(extracted),
        "scene": str(scene),
        "rules": {
            "hash": "low32(mesh_hash(normalized_logical_path)) matches the final eight hex digits of decoded filenames",
            "scene_mesh": "AllFiles .gim path with extension replaced by .mesh",
            "material_policy": "apply MTL only when an explicit unique path/reference is present; otherwise preserve shape-only output and record unresolved",
            "source_policy": "decoded source files are read-only; outputs are written under converted/",
        },
        "scene_file_count": len(file_paths),
        "scene_model_instance_count": len(instances),
        "scene_unique_gim_count": len(unique_gims),
        "selected_unique_gim_count": len(selected_gims),
        "converted_mesh_count": converted_count,
        "unresolved_asset_count": len(unresolved),
        "decoded_texture_count": texture_count,
        "assets": assets,
        "instances": instances,
    }
    (output / "batch_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "unresolved.json").write_text(json.dumps(unresolved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"[summary] selected={len(selected_gims)} converted={converted_count} unresolved={len(unresolved)} textures={texture_count}")
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    return 0 if converted_count > 0 or not selected_gims else 2


if __name__ == "__main__":
    raise SystemExit(main())
