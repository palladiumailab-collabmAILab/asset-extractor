#!/usr/bin/env python3
"""Build evidence-backed textured static glTF files for the qmodel pilot.

This is deliberately a publication stage.  It reads an existing, verified
pilot extraction and writes a new output directory without changing raw files.
NeoXtractor supplies the path hash, mesh parser, image decoder, and glTF
exporter.  A mesh is published only when one material document, every Tex0
texture, and the ordered submesh/material counts resolve without ambiguity.
"""

from __future__ import annotations

import argparse
import base64
import copy
import importlib.metadata
import importlib.util
import json
import math
import re
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable

from runtime_artifacts import (
    json_bytes,
    sha256_bytes,
    sha256_file,
    utc_now,
    write_bytes_atomic,
)

HASH_SUFFIX = re.compile(r"([0-9a-fA-F]{8})$")
IMAGE_EXTENSIONS = ("png", "jpg", "jpeg", "tga", "bmp", "dds", "ktx", "pvr", "astc")
RUNTIME_DEPENDENCIES = {
    "PIL": "Pillow",
    "numpy": "numpy",
    "texture2ddecoder": "texture2ddecoder",
}


class PublicationError(ValueError):
    pass


def load_neoxtractor_modules(source_tree: Path) -> tuple[Any, Any, Any, Any, Any]:
    """Load the pinned upstream components without leaking import-path state."""

    original_sys_path = sys.path.copy()
    sys.path.insert(0, str(source_tree))
    try:
        from core.images import convert_image  # type: ignore[import-not-found]
        from core.mesh_converter.formats import gltf  # type: ignore[import-not-found]
        from core.mesh_loader import MeshLoader  # type: ignore[import-not-found]
        from core.mesh_loader.types import Bones  # type: ignore[import-not-found]
        from core.npk.npkhash_v1 import mesh_hash  # type: ignore[import-not-found]
        return convert_image, gltf, MeshLoader, Bones, mesh_hash
    finally:
        # Importing an upstream package may add more entries than the one we
        # supplied, so restore the complete caller state.
        sys.path[:] = original_sys_path


def runtime_dependency_report() -> dict[str, dict[str, Any]]:
    report: dict[str, dict[str, Any]] = {}
    for module_name, distribution_name in RUNTIME_DEPENDENCIES.items():
        available = importlib.util.find_spec(module_name) is not None
        version: str | None = None
        if available:
            try:
                version = importlib.metadata.version(distribution_name)
            except importlib.metadata.PackageNotFoundError:
                version = None
        report[module_name] = {
            "distribution": distribution_name,
            "available": available,
            "version": version,
        }
    return report


def missing_runtime_dependencies(report: dict[str, dict[str, Any]]) -> list[str]:
    return sorted(name for name, row in report.items() if not row.get("available"))


def publication_status(outputs: list[dict[str, Any]]) -> str:
    """Return the manifest status from the actual per-model outcomes."""

    if not outputs:
        return "failed"
    converted = sum(row.get("status") == "converted" for row in outputs)
    if converted == len(outputs):
        return "complete"
    return "partial" if converted else "failed"


def status_exit_code(status: str) -> int:
    return {"complete": 0, "partial": 1, "failed": 2}.get(status, 2)


def maybe_delegate_runtime(
    raw_argv: list[str],
    runtime_python: Path | None,
    runtime_active: bool,
) -> int | None:
    if runtime_python is None or runtime_active:
        return None
    runtime = runtime_python.expanduser().resolve()
    if not runtime.is_file():
        raise PublicationError(f"runtime Python is unavailable: {runtime}")
    if runtime == Path(sys.executable).resolve():
        return None
    completed = subprocess.run(
        [str(runtime), str(Path(__file__).resolve()), *raw_argv, "--_runtime-active"],
        check=False,
    )
    return completed.returncode


def write_atomic(path: Path, data: bytes) -> None:
    try:
        write_bytes_atomic(path, data, overwrite=False)
    except FileExistsError as exc:
        raise PublicationError(f"refusing to overwrite output: {path}") from exc


def normalized_logical_path(value: str) -> str:
    return value.replace("/", "\\").lower()


def logical_image_variants(value: str) -> list[str]:
    normalized = normalized_logical_path(value)
    leaf = normalized.rsplit("\\", 1)[-1]
    stem = normalized.rsplit(".", 1)[0] if "." in leaf else normalized
    return list(dict.fromkeys([normalized, *(f"{stem}.{extension}" for extension in IMAGE_EXTENSIONS)]))


def ordered_material_slots(material_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = ET.parse(material_path).getroot()
    group = next(root.iter("MaterialGroup"), None)
    if group is None:
        raise PublicationError("MaterialGroup is missing")
    slots: list[dict[str, Any]] = []
    for ordinal, wrapper in enumerate(list(group)):
        material = next(wrapper.iter("Material"), None)
        if material is None:
            raise PublicationError(f"{wrapper.tag} contains no Material")
        param_table = next(material.iter("ParamTable"), None)
        tex0_nodes = [] if param_table is None else [node for node in list(param_table) if node.tag.lower() == "tex0"]
        tex0_values = [node.attrib.get("Value", "") for node in tex0_nodes if node.attrib.get("Value")]
        technique = next(material.iter("Technique"), None)
        render_states = next(material.iter("RenderStates"), None)
        transparent = next(material.iter("TransparentMode"), None)
        slots.append(
            {
                "ordinal": ordinal,
                "wrapper": wrapper.tag,
                "name": material.attrib.get("Name", ""),
                "tex0_values": tex0_values,
                "technique": technique.attrib.get("TechName") if technique is not None else None,
                "alpha_ref": render_states.attrib.get("AlphaRef") if render_states is not None else None,
                "cull_mode": render_states.attrib.get("CullMode") if render_states is not None else None,
                "transparent_mode": transparent.attrib.get("TransparentMode") if transparent is not None else None,
            }
        )
    declared = int(group.attrib.get("MaterialCount", len(slots)))
    return {"declared_material_count": declared, "group_name": group.attrib.get("Name", "")}, slots


def mesh_logical_candidates(slots: Iterable[dict[str, Any]]) -> list[str]:
    candidates: set[str] = set()
    for slot in slots:
        for reference in slot.get("tex0_values", []):
            normalized = reference.replace("\\", "/")
            directory = normalized.rsplit("/", 1)[0] if "/" in normalized else ""
            folder = directory.rsplit("/", 1)[-1] if directory else ""
            if folder:
                candidates.add(f"{directory}/{folder}.mesh")
            name = str(slot.get("name") or "")
            if name:
                candidates.add(f"{directory}/{name}.mesh" if directory else f"{name}.mesh")
    return sorted(candidates, key=str.lower)


def material_binding_signature(record: dict[str, Any]) -> tuple[Any, ...]:
    """Return only fields that affect Tex0/submesh material binding.

    Some NeoX builds contain duplicate material documents that differ only in
    display names (for example ``Material #0`` versus ``s3_hairen``).  Such
    documents are safe to coalesce only when all binding/render-state fields
    are identical; names and source paths are intentionally excluded.
    """
    slots = []
    for slot in record.get("slots", []):
        slots.append(
            (
                tuple(normalized_logical_path(str(value)) for value in slot.get("tex0_values", [])),
                str(slot.get("technique") or "").lower(),
                str(slot.get("alpha_ref") or ""),
                str(slot.get("cull_mode") or ""),
                str(slot.get("transparent_mode") or ""),
            )
        )
    return (
        int(record.get("declared_material_count", len(slots))),
        str(record.get("group_name") or ""),
        tuple(slots),
    )


def safe_raw_path(run_root: Path, value: str) -> Path:
    path = Path(value).resolve()
    try:
        path.relative_to(run_root)
    except ValueError as exc:
        raise PublicationError(f"raw path escapes run root: {path}") from exc
    if not path.is_file() or path.is_symlink():
        raise PublicationError(f"raw file is missing or unsafe: {path}")
    return path


def load_catalog(run_roots: Iterable[Path]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    entries: list[dict[str, Any]] = []
    by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run_root in run_roots:
        classification_path = run_root / "type-classification.json"
        classification = json.loads(classification_path.read_text(encoding="utf-8"))
        if classification.get("status") != "complete":
            raise PublicationError(f"type classification is not complete: {classification_path}")
        for source in classification.get("outputs", []):
            row = dict(source)
            path = safe_raw_path(run_root, str(row.get("path", "")))
            actual_size = path.stat().st_size
            actual_sha = sha256_file(path)
            if actual_size != row.get("bytes") or actual_sha != row.get("sha256"):
                raise PublicationError(f"raw source verification failed: {path}")
            match = HASH_SUFFIX.search(path.stem)
            row["path"] = str(path)
            row["source_run"] = str(run_root)
            row["payload_hash_low32"] = match.group(1).lower() if match else None
            entries.append(row)
            if match:
                by_hash[match.group(1).lower()].append(row)
    return entries, dict(by_hash)


def resolve_rows(by_hash: dict[str, list[dict[str, Any]]], keys: Iterable[str], category: str) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for key in keys:
        for row in by_hash.get(key.lower(), []):
            if row.get("category") == category:
                rows[str(row["sha256"])] = row
    return list(rows.values())


def capture_mesh_parts(mesh_loader_class: Any, source: Path) -> tuple[Any, list[tuple[int, int, int, int]]]:
    """Use NeoXtractor's parser while retaining its ordered submesh header."""

    loader = mesh_loader_class()
    if not getattr(loader, "_parsers", None):
        raise PublicationError("NeoXtractor MeshLoader has no parser")
    parser = loader._parsers[0]
    original = parser._standardize_mesh_data
    captured: dict[str, Any] = {}

    def wrapper(model: dict[str, Any]):
        captured["model"] = model
        return original(model)

    parser._standardize_mesh_data = wrapper
    try:
        mesh = loader.load_from_file(source)
    finally:
        parser._standardize_mesh_data = original
    if mesh is None:
        raise PublicationError("NeoXtractor MeshLoader rejected this mesh variant")
    parts = list(captured.get("model", {}).get("mesh", {}).get("extra") or [])
    if not parts:
        raise PublicationError("NeoXtractor did not expose an ordered submesh header")
    normalized_parts = [tuple(int(value) for value in part) for part in parts]
    if sum(part[0] for part in normalized_parts) != int(mesh.vertex_count):
        raise PublicationError("submesh vertex counts do not sum to total")
    if sum(part[1] for part in normalized_parts) != int(mesh.face_count):
        raise PublicationError("submesh face counts do not sum to total")
    face_cursor = 0
    vertex_cursor = 0
    for vertex_count, face_count, _uv_layers, _unknown in normalized_parts:
        faces = mesh.mesh.face[face_cursor : face_cursor + face_count]
        indices = [index for face in faces for index in face]
        if len(faces) != face_count or not indices:
            raise PublicationError("submesh face slice is empty or truncated")
        if min(indices) < vertex_cursor or max(indices) >= vertex_cursor + vertex_count:
            raise PublicationError("submesh indices cross the declared vertex range")
        face_cursor += face_count
        vertex_cursor += vertex_count
    return mesh, normalized_parts


def png_from_source(source: Path, convert_image: Any) -> tuple[bytes, int, int, bool]:
    from PIL import Image

    extension = source.suffix.lower().lstrip(".")
    data = source.read_bytes()
    if extension in {"png", "jpg", "jpeg", "bmp", "tga"}:
        image = Image.open(BytesIO(data)).convert("RGBA")
    else:
        image = convert_image(data, extension)
        if image is None:
            raise PublicationError(f"NeoXtractor decoder does not support {extension}")
        image = image.convert("RGBA")
    width, height = image.size
    if width <= 0 or height <= 0 or width * height > 67_108_864:
        raise PublicationError(f"invalid texture dimensions: {width}x{height}")
    alpha_used = image.getextrema()[3][0] < 255
    output = BytesIO()
    image.save(output, "PNG")
    payload = output.getvalue()
    with Image.open(BytesIO(payload)) as check:
        check.verify()
    return payload, width, height, alpha_used


def split_primitives_and_attach_materials(
    document: dict[str, Any],
    parts: list[tuple[int, int, int, int]],
    material_slots: list[dict[str, Any]],
    texture_payloads: list[dict[str, Any]],
    association: str = "ordered NeoX submesh to ordered Material_N; exact counts required",
) -> dict[str, Any]:
    if len(parts) != len(material_slots) or len(parts) != len(texture_payloads):
        raise PublicationError("submesh/material/texture counts differ")
    primitive = document["meshes"][0]["primitives"][0]
    index_accessor = document["accessors"][primitive["indices"]]
    component_size = {5121: 1, 5123: 2, 5125: 4}.get(index_accessor.get("componentType"))
    if component_size is None or index_accessor.get("type") != "SCALAR":
        raise PublicationError("unsupported glTF index accessor")
    cursor = 0
    primitives = []
    for ordinal, part in enumerate(parts):
        face_count = part[1]
        accessor = copy.deepcopy(index_accessor)
        accessor["count"] = face_count * 3
        accessor["byteOffset"] = int(index_accessor.get("byteOffset", 0)) + cursor * 3 * component_size
        accessor_index = len(document["accessors"])
        document["accessors"].append(accessor)
        item = copy.deepcopy(primitive)
        item["indices"] = accessor_index
        item["material"] = ordinal
        primitives.append(item)
        cursor += face_count
    document["meshes"][0]["primitives"] = primitives
    document["images"] = []
    document["textures"] = []
    document["samplers"] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]
    document["materials"] = []
    for ordinal, (slot, texture) in enumerate(zip(material_slots, texture_payloads)):
        document["images"].append(
            {
                "name": f"Tex0_{ordinal}_{slot.get('name') or 'material'}",
                "mimeType": "image/png",
                "uri": "data:image/png;base64," + base64.b64encode(texture["png_bytes"]).decode("ascii"),
            }
        )
        document["textures"].append({"sampler": 0, "source": ordinal})
        material: dict[str, Any] = {
            "name": slot.get("name") or f"Material_{ordinal}",
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": ordinal},
                "metallicFactor": 0.0,
                "roughnessFactor": 1.0,
            },
            "extras": {
                "association": association,
                "tex0_logical_path": slot["tex0_values"][0],
                "technique": slot.get("technique"),
                "transparent_mode": slot.get("transparent_mode"),
                "alpha_ref": slot.get("alpha_ref"),
                "cull_mode": slot.get("cull_mode"),
            },
        }
        try:
            alpha_ref = int(slot.get("alpha_ref") or 0)
            transparent_mode = int(slot.get("transparent_mode") or 0)
        except ValueError:
            alpha_ref = transparent_mode = 0
        if alpha_ref > 0:
            material["alphaMode"] = "MASK"
            material["alphaCutoff"] = min(1.0, max(0.0, alpha_ref / 255.0))
        elif transparent_mode > 0 and texture.get("alpha_used"):
            material["alphaMode"] = "BLEND"
        document["materials"].append(material)
    document.setdefault("extras", {})["publication_policy"] = {
        "scope": "textured static inspection; skeleton and animation intentionally omitted",
        "tex0_bridge": "Tex0 is presented as glTF baseColorTexture; original NeoX shader remains in material extras",
        "submesh_bridge": "ordered headers are paired only when counts exactly match ordered Material_N records",
    }
    document["asset"]["generator"] = str(document["asset"].get("generator", "NeoXtractor")) + " + asset-extractor textured pilot"
    return document


def validate_gltf(document: dict[str, Any], parts: list[tuple[int, int, int, int]]) -> dict[str, Any]:
    from PIL import Image

    encoded = json.dumps(document, ensure_ascii=False, allow_nan=False)
    if not encoded:
        raise PublicationError("empty glTF")
    primitives = document.get("meshes", [{}])[0].get("primitives", [])
    if len(primitives) != len(parts):
        raise PublicationError("glTF primitive count differs from submesh count")
    if not (len(document.get("materials", [])) == len(document.get("textures", [])) == len(document.get("images", [])) == len(parts)):
        raise PublicationError("glTF material/texture/image counts differ")
    buffers = []
    for item in document.get("buffers", []):
        uri = item.get("uri", "")
        if not uri.startswith("data:") or "," not in uri:
            raise PublicationError("glTF buffer is not embedded")
        payload = base64.b64decode(uri.split(",", 1)[1], validate=True)
        if len(payload) < int(item.get("byteLength", 0)):
            raise PublicationError("glTF embedded buffer is truncated")
        buffers.append(payload)
    component = {5120: (1, "b"), 5121: (1, "B"), 5122: (2, "h"), 5123: (2, "H"), 5125: (4, "I"), 5126: (4, "f")}
    element_count = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
    decoded_accessors: dict[int, list[Any]] = {}
    for index, accessor in enumerate(document.get("accessors", [])):
        view = document["bufferViews"][accessor["bufferView"]]
        size, fmt = component[accessor["componentType"]]
        width = element_count[accessor["type"]]
        stride = int(view.get("byteStride", size * width))
        start = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
        end = start if not accessor["count"] else start + (int(accessor["count"]) - 1) * stride + size * width
        view_end = int(view.get("byteOffset", 0)) + int(view["byteLength"])
        raw = buffers[int(view["buffer"])]
        if end > view_end or end > len(raw):
            raise PublicationError(f"accessor {index} exceeds buffer view")
        if accessor["componentType"] in {5123, 5125} and accessor["type"] == "SCALAR":
            decoded_accessors[index] = [struct.unpack_from("<" + fmt, raw, start + row * stride)[0] for row in range(int(accessor["count"]))]
        if accessor["componentType"] == 5126:
            for row in range(int(accessor["count"])):
                values = struct.unpack_from("<" + fmt * width, raw, start + row * stride)
                if not all(math.isfinite(value) for value in values):
                    raise PublicationError(f"accessor {index} contains non-finite values")
    position_count = int(document["accessors"][primitives[0]["attributes"]["POSITION"]]["count"])
    vertex_cursor = 0
    for primitive, part in zip(primitives, parts):
        indices = decoded_accessors[int(primitive["indices"])]
        if not indices or min(indices) < vertex_cursor or max(indices) >= vertex_cursor + part[0] or max(indices) >= position_count:
            raise PublicationError("glTF submesh index bounds are invalid")
        vertex_cursor += part[0]
    for image in document["images"]:
        payload = base64.b64decode(image["uri"].split(",", 1)[1], validate=True)
        with Image.open(BytesIO(payload)) as check:
            check.verify()
    return {
        "json_finite": True,
        "accessor_bounds": True,
        "index_bounds": True,
        "embedded_png_verify": True,
        "primitive_count": len(primitives),
        "material_count": len(document["materials"]),
        "texture_count": len(document["textures"]),
        "image_count": len(document["images"]),
    }


def load_material_records(
    entries: list[dict[str, Any]],
    by_hash: dict[str, list[dict[str, Any]]],
    mesh_hash: Any,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, dict[str, Any]]]]:
    """Parse material catalogs and resolve each material to mesh payloads."""

    material_records: list[dict[str, Any]] = []
    material_by_mesh: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in entries:
        if row.get("category") != "material":
            continue
        record: dict[str, Any] = {
            "source": row["path"],
            "source_sha256": row["sha256"],
            "status": "unresolved",
            "reasons": [],
        }
        try:
            group, slots = ordered_material_slots(Path(row["path"]))
            record.update(group)
            record["slots"] = slots
            candidates = mesh_logical_candidates(slots)
            record["mesh_logical_candidates"] = candidates
            matched: dict[str, dict[str, Any]] = {}
            matched_logicals: dict[str, list[str]] = defaultdict(list)
            for logical in candidates:
                key = f"{mesh_hash(normalized_logical_path(logical)):08x}"
                for match in resolve_rows(by_hash, [key], "mesh"):
                    matched[str(match["sha256"])] = match
                    matched_logicals[str(match["sha256"])].append(logical)
            record["matched_meshes"] = [
                {"sha256": digest, "path": match["path"], "logical_paths": matched_logicals[digest]}
                for digest, match in matched.items()
            ]
            if len(matched) == 1:
                record["status"] = "resolved-to-one-mesh-payload"
                digest = next(iter(matched))
                record["resolved_mesh_sha256"] = digest
                material_by_mesh[digest][record["source_sha256"]] = record
            elif not matched:
                record["reasons"].append("no_mesh_hash_match")
            else:
                record["reasons"].append("multiple_mesh_payload_matches")
        except Exception as exc:  # noqa: BLE001 - retain one record per upstream parse failure
            record["reasons"].append(f"material_parse_failed:{exc}")
        material_records.append(record)
    return material_records, material_by_mesh


def resolve_texture_output(
    reference: str,
    by_hash: dict[str, list[dict[str, Any]]],
    mesh_hash: Any,
    convert_image: Any,
    output: Path,
    texture_outputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Resolve one Tex0 reference and publish its PNG once per content hash."""

    variants = logical_image_variants(reference)
    keyed = [(variant, f"{mesh_hash(normalized_logical_path(variant)):08x}") for variant in variants]
    matches = resolve_rows(by_hash, [key for _variant, key in keyed], "texture")
    if len(matches) != 1:
        raise PublicationError(f"Tex0 did not resolve uniquely: {reference} ({len(matches)} payloads)")
    texture_row = matches[0]
    chosen = [
        variant
        for variant, key in keyed
        if any(
            candidate["sha256"] == texture_row["sha256"]
            for candidate in resolve_rows(by_hash, [key], "texture")
        )
    ]
    png, width, height, alpha_used = png_from_source(Path(texture_row["path"]), convert_image)
    png_sha = sha256_bytes(png)
    texture_target = output / "textures" / png_sha[:2] / f"{png_sha}.png"
    if png_sha not in texture_outputs:
        write_atomic(texture_target, png)
        texture_outputs[png_sha] = {
            "source": texture_row["path"],
            "source_sha256": texture_row["sha256"],
            "logical_reference": reference,
            "matched_logical_variants": chosen,
            "output": str(texture_target),
            "output_sha256": png_sha,
            "output_bytes": len(png),
            "width": width,
            "height": height,
            "alpha_used": alpha_used,
            "status": "converted",
        }
    return {**texture_outputs[png_sha], "png_bytes": png}


def publish_mesh(
    *,
    mesh_sha: str,
    source_rows: list[dict[str, Any]],
    material_by_mesh: dict[str, dict[str, dict[str, Any]]],
    material_overrides: dict[str, dict[str, Any]],
    allow_equivalent_material_duplicates: bool,
    by_hash: dict[str, list[dict[str, Any]]],
    output: Path,
    texture_outputs: dict[str, dict[str, Any]],
    mesh_loader: Any,
    bones: Any,
    mesh_hash: Any,
    convert_image: Any,
    gltf: Any,
) -> tuple[dict[str, Any], bool]:
    """Resolve, convert, validate, and publish one mesh family."""

    source = Path(source_rows[0]["path"])
    item: dict[str, Any] = {
        "mesh_sha256": mesh_sha,
        "source": str(source),
        "duplicate_source_paths": [row["path"] for row in source_rows],
        "status": "unresolved",
        "reasons": [],
    }
    override = material_overrides.get(mesh_sha.lower())
    documents = list(material_by_mesh.get(mesh_sha, {}).values())
    if override is not None:
        selected_documents = [
            document
            for document in documents
            if str(document.get("source_sha256", "")).lower() == override["material_source_sha256"]
        ]
        if len(selected_documents) != 1:
            item["reasons"].append("material_override_source_not_unique")
            item["material_candidates"] = [record["source"] for record in documents]
            item["material_override"] = override
            return item, True
        documents = selected_documents

    material_resolution: dict[str, Any] | None = None
    if len(documents) != 1 and allow_equivalent_material_duplicates and documents:
        signatures = {material_binding_signature(document) for document in documents}
        if len(signatures) == 1:
            chosen = min(
                documents,
                key=lambda document: (
                    str(document.get("source_sha256", "")),
                    str(document.get("source", "")),
                ),
            )
            material_resolution = {
                "policy": "equivalent_binding_signature",
                "candidate_count": len(documents),
                "candidate_sources": [document["source"] for document in documents],
                "chosen_source": chosen["source"],
            }
            documents = [chosen]
    if len(documents) != 1:
        item["reasons"].append(
            "no_unique_material_document" if not documents else "multiple_material_documents"
        )
        item["material_candidates"] = [record["source"] for record in documents]
        return item, True

    material = documents[0]
    original_slots = material["slots"]
    slots = original_slots
    item["material_source"] = material["source"]
    item["material_sha256"] = material["source_sha256"]
    item["mesh_logical_paths"] = material["matched_meshes"][0]["logical_paths"]
    if material_resolution is not None:
        item["material_resolution"] = material_resolution
    if override is not None:
        if any(index >= len(original_slots) for index in override["slot_indices"]):
            item["reasons"].append("material_override_slot_index_out_of_range")
            item["material_override"] = override
            return item, True
        slots = [copy.deepcopy(original_slots[index]) for index in override["slot_indices"]]
        for ordinal, slot in enumerate(slots):
            slot["ordinal"] = ordinal
        item["material_override"] = {
            **override,
            "original_slot_count": len(original_slots),
            "expanded_slot_count": len(slots),
        }

    try:
        if material["declared_material_count"] != len(slots):
            if override is None or material["declared_material_count"] != len(original_slots):
                raise PublicationError("declared MaterialCount differs from Material_N records")
        if any(len(slot.get("tex0_values", [])) != 1 for slot in slots):
            raise PublicationError("every Material_N must contain exactly one Tex0")
        mesh, parts = capture_mesh_parts(mesh_loader, source)
        if len(parts) != len(slots):
            raise PublicationError("ordered submesh count differs from ordered Material_N count")
        uv_input_count = len(mesh.mesh.uv)
        vertex_count = int(mesh.vertex_count)
        if uv_input_count != vertex_count:
            if uv_input_count < vertex_count or uv_input_count % vertex_count:
                raise PublicationError("mesh has an incomplete UV block")
            mesh.mesh.uv = mesh.mesh.uv[:vertex_count]
            item["uv_policy"] = {
                "policy": "first_vertex_sized_block_as_texcoord_0",
                "input_uv_count": uv_input_count,
                "output_uv_count": vertex_count,
                "input_blocks": uv_input_count // vertex_count,
            }

        resolved_textures = [
            resolve_texture_output(
                slot["tex0_values"][0],
                by_hash,
                mesh_hash,
                convert_image,
                output,
                texture_outputs,
            )
            for slot in slots
        ]
        mesh.bones = bones()
        document = json.loads(gltf.convert(mesh).decode("utf-8"))
        association = (
            "explicit audited submesh slot map; source Material_N slots selected by SHA-256; "
            "repeated slots are intentional and recorded in material_override"
            if override is not None
            else "ordered NeoX submesh to ordered Material_N; exact counts required"
        )
        document = split_primitives_and_attach_materials(
            document, parts, slots, resolved_textures, association
        )
        if override is not None:
            document.setdefault("extras", {})["material_override"] = item["material_override"]
        validation = validate_gltf(document, parts)
        target = output / "models" / mesh_sha[:2] / f"{mesh_sha}.gltf"
        payload = json_bytes(document)
        write_atomic(target, payload)
        association_evidence = (
            "explicit audited submesh slot map; source material selected by SHA-256; "
            "ordered mapped slots equal observed submeshes; every Tex0 resolves to one texture payload"
            if override is not None
            else (
                "equivalent duplicate material documents; binding signatures identical; deterministic source selected; "
                "ordered submesh and Material_N counts equal; every Tex0 resolves to one texture payload"
                if material_resolution is not None
                else "one material document; one mesh payload; ordered submesh and Material_N counts equal; every Tex0 resolves to one texture payload"
            )
        )
        item.update(
            {
                "status": "converted",
                "output": str(target),
                "output_sha256": sha256_bytes(payload),
                "output_bytes": len(payload),
                "vertex_count": int(mesh.vertex_count),
                "face_count": int(mesh.face_count),
                "uv_count": len(mesh.mesh.uv),
                "submeshes": [
                    {
                        "ordinal": index,
                        "vertices": part[0],
                        "faces": part[1],
                        "uv_layers": part[2],
                        "unknown": part[3],
                    }
                    for index, part in enumerate(parts)
                ],
                "materials": [
                    {
                        "ordinal": slot["ordinal"],
                        "name": slot["name"],
                        "tex0": slot["tex0_values"][0],
                        "texture_source_sha256": texture["source_sha256"],
                        "texture_output_sha256": texture["output_sha256"],
                        "technique": slot.get("technique"),
                    }
                    for slot, texture in zip(slots, resolved_textures)
                ],
                "validation": validation,
                "static_only": True,
                "skeleton_omitted": True,
                "animation_omitted": True,
                "association_evidence": association_evidence,
            }
        )
    except Exception as exc:  # noqa: BLE001 - preserve one auditable row per mesh failure
        item["reasons"].append(str(exc))
    return item, item["status"] != "converted"


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--catalog-run", action="append", default=[], type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-tree", required=True, type=Path)
    parser.add_argument(
        "--allow-equivalent-material-duplicates",
        action="store_true",
        help="coalesce duplicate material documents only when all Tex0/render-state bindings match",
    )
    parser.add_argument(
        "--only-mesh-sha256",
        action="append",
        default=[],
        help="publish only the specified mesh SHA-256 values (repeatable)",
    )
    parser.add_argument(
        "--material-overrides",
        type=Path,
        help=(
            "JSON audit configuration for explicit mesh->material source and ordered slot mappings; "
            "disabled unless supplied"
        ),
    )
    parser.add_argument(
        "--runtime-python",
        type=Path,
        help="Python executable containing NeoXtractor image-decoder dependencies",
    )
    parser.add_argument("--_runtime-active", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(raw_argv)
    try:
        delegated = maybe_delegate_runtime(raw_argv, args.runtime_python, args._runtime_active)
    except PublicationError as exc:
        print(f"textured publication failed: {exc}", file=sys.stderr)
        return 2
    if delegated is not None:
        return delegated

    run_root = args.run_root.resolve()
    catalog_roots = [run_root, *(path.resolve() for path in args.catalog_run)]
    output = args.output.resolve()
    source_tree = args.source_tree.resolve()
    if output.exists():
        raise SystemExit(f"output already exists: {output}")
    if not source_tree.is_dir():
        raise SystemExit(f"NeoXtractor source tree missing: {source_tree}")

    dependency_report = runtime_dependency_report()
    missing_dependencies = missing_runtime_dependencies(dependency_report)
    if missing_dependencies:
        print(
            "textured publication failed: runtime dependency preflight missing "
            + ", ".join(missing_dependencies),
            file=sys.stderr,
        )
        return 2
    runtime_metadata = {
        "executable": str(Path(sys.executable).resolve()),
        "version": sys.version.split()[0],
        "requested_executable": str(args.runtime_python.expanduser().resolve()) if args.runtime_python else None,
        "delegated": bool(args._runtime_active),
        "dependencies": dependency_report,
        "preflight_complete": True,
    }

    material_overrides: dict[str, dict[str, Any]] = {}
    material_overrides_path: Path | None = None
    if args.material_overrides is not None:
        material_overrides_path = args.material_overrides.resolve()
        if not material_overrides_path.is_file():
            raise SystemExit(f"material override configuration missing: {material_overrides_path}")
        try:
            override_document = json.loads(material_overrides_path.read_text(encoding="utf-8"))
            raw_overrides = override_document.get("overrides")
            if not isinstance(raw_overrides, dict):
                raise ValueError("overrides must be an object")
            for raw_mesh_sha, raw_spec in raw_overrides.items():
                mesh_sha = str(raw_mesh_sha).strip().lower()
                if not re.fullmatch(r"[0-9a-f]{64}", mesh_sha):
                    raise ValueError(f"invalid mesh SHA-256 key: {raw_mesh_sha}")
                if not isinstance(raw_spec, dict):
                    raise ValueError(f"override for {mesh_sha} must be an object")
                material_sha = str(raw_spec.get("material_source_sha256", "")).strip().lower()
                if not re.fullmatch(r"[0-9a-f]{64}", material_sha):
                    raise ValueError(f"invalid material SHA-256 for {mesh_sha}")
                slot_indices = raw_spec.get("slot_indices")
                if (
                    not isinstance(slot_indices, list)
                    or not slot_indices
                    or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in slot_indices)
                ):
                    raise ValueError(f"slot_indices for {mesh_sha} must be a non-empty list of non-negative integers")
                material_overrides[mesh_sha] = {
                    "material_source_sha256": material_sha,
                    "slot_indices": list(slot_indices),
                    "reason": str(raw_spec.get("reason", "")),
                }
        except (OSError, json.JSONDecodeError, ValueError, AttributeError) as exc:
            raise SystemExit(f"invalid material override configuration: {exc}") from exc

    try:
        convert_image, gltf, MeshLoader, Bones, mesh_hash = load_neoxtractor_modules(source_tree)
    except (ImportError, ModuleNotFoundError) as exc:
        print(f"textured publication failed: NeoXtractor import preflight: {exc}", file=sys.stderr)
        return 2
    output.mkdir(parents=True)

    entries, by_hash = load_catalog(catalog_roots)
    mesh_rows_by_sha: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in entries:
        if row.get("category") == "mesh":
            mesh_rows_by_sha[str(row["sha256"])].append(row)
    if args.only_mesh_sha256:
        selected = {value.strip().lower() for value in args.only_mesh_sha256}
        mesh_rows_by_sha = {
            digest: rows for digest, rows in mesh_rows_by_sha.items() if digest.lower() in selected
        }

    material_records, material_by_mesh = load_material_records(entries, by_hash, mesh_hash)

    outputs: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    texture_outputs: dict[str, dict[str, Any]] = {}
    for mesh_sha, source_rows in sorted(mesh_rows_by_sha.items()):
        item, is_unresolved = publish_mesh(
            mesh_sha=mesh_sha,
            source_rows=source_rows,
            material_by_mesh=material_by_mesh,
            material_overrides=material_overrides,
            allow_equivalent_material_duplicates=args.allow_equivalent_material_duplicates,
            by_hash=by_hash,
            output=output,
            texture_outputs=texture_outputs,
            mesh_loader=MeshLoader,
            bones=Bones,
            mesh_hash=mesh_hash,
            convert_image=convert_image,
            gltf=gltf,
        )
        if is_unresolved:
            unresolved.append(item)
        outputs.append(item)

    differential_path = run_root / "differential.json"
    if not differential_path.is_file():
        differential_path = run_root / "oracle-comparison.json"
    differential = json.loads(differential_path.read_text(encoding="utf-8")) if differential_path.is_file() else {}
    provenance_path = run_root / "tool-provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8")) if provenance_path.is_file() else {}
    raw_manifest_path = run_root / "raw-extraction-manifest.json"
    if not raw_manifest_path.is_file():
        raw_manifest_path = run_root / "production" / "run-manifest.json"
    neox_metadata = provenance.get("tools", {}).get("NeoXtractor") or differential.get("NeoXtractor", {}).get("tool_metadata")
    neox_tools_metadata = provenance.get("tools", {}).get("neox_tools") or differential.get("neox_tools", {}).get("tool_metadata")
    oracle_gate = differential.get("gate") or differential.get("comparison")
    resolver = {
        "schema_version": 1,
        "stage": "pilot-static-resolver",
        "created_at": utc_now(),
        "run_root": str(run_root),
        "policy": {
            "hash": "low32 NeoX mesh_hash(normalized logical path)",
            "texture_variants": list(IMAGE_EXTENSIONS),
            "ambiguity": "fail closed; never choose among multiple material, mesh, or texture payloads",
            "equivalent_material_duplicates": (
                "enabled: coalesce only identical Tex0/render-state signatures; choose lowest source SHA-256"
                if args.allow_equivalent_material_duplicates
                else "disabled"
            ),
            "submesh_material": (
                "explicit slot mappings are permitted only through the supplied audit configuration; "
                "default remains exact ordered count matching"
                if material_overrides
                else "ordered pairing only when declared and observed counts exactly match"
            ),
        },
        "runtime": runtime_metadata,
        "materials": material_records,
    }
    manifest = {
        "schema_version": 1,
        "stage": "textured-static-pilot",
        "created_at": utc_now(),
        "status": publication_status(outputs),
        "source_policy": "read-only",
        "run_root": str(run_root),
        "catalog_runs": [str(path) for path in catalog_roots],
        "output_root": str(output),
        "counts": {
            "unique_meshes": len(mesh_rows_by_sha),
            "converted": sum(row["status"] == "converted" for row in outputs),
            "unresolved": sum(row["status"] != "converted" for row in outputs),
            "unique_textures_published": len(texture_outputs),
        },
        "tools": {
            "NeoXtractor": neox_metadata,
            "neox_tools": neox_tools_metadata,
            "neox_tools_oracle_gate": oracle_gate,
            "publication_script": {"path": str(Path(__file__).resolve()), "sha256": sha256_file(Path(__file__).resolve())},
            "runtime": runtime_metadata,
        },
        "source_manifests": {
            "raw": {"path": str(raw_manifest_path), "sha256": sha256_file(raw_manifest_path)},
            "classification": {"path": str(run_root / "type-classification.json"), "sha256": sha256_file(run_root / "type-classification.json")},
            "differential": {"path": str(differential_path), "sha256": sha256_file(differential_path)},
        },
        "models": outputs,
        "textures": list(texture_outputs.values()),
        "raw_outputs_immutable": True,
        "animation_stage": "not-run-by-design",
    }
    if material_overrides_path is not None:
        manifest["source_manifests"]["material_overrides"] = {
            "path": str(material_overrides_path),
            "sha256": sha256_file(material_overrides_path),
            "entries": len(material_overrides),
        }
    write_atomic(output / "resolver-manifest.json", json_bytes(resolver))
    write_atomic(output / "textured-static-manifest.json", json_bytes(manifest))
    write_atomic(output / "unresolved.json", json_bytes(unresolved))
    print(json.dumps(manifest["counts"], ensure_ascii=False))
    return status_exit_code(manifest["status"])


if __name__ == "__main__":
    raise SystemExit(main())
