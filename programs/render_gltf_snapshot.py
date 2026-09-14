#!/usr/bin/env python3
"""Render a self-contained textured glTF snapshot with a small PIL rasterizer.

This is an inspection aid for environments without Blender/WebGL capture.  It
reads only the glTF JSON/data-URI payload, applies the embedded base-color
texture, and writes a PNG plus a short provenance report.  It is deliberately
not a general glTF runtime and does not execute embedded payloads.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import urllib.parse
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from runtime_artifacts import sha256_file


COMPONENTS: dict[int, tuple[str, int]] = {
    5120: ("i1", 1),
    5121: ("u1", 1),
    5122: ("<i2", 2),
    5123: ("<u2", 2),
    5125: ("<u4", 4),
    5126: ("<f4", 4),
}
TYPE_COUNTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}


def data_uri_bytes(uri: str) -> bytes:
    header, body = uri.split(",", 1)
    if ";base64" in header:
        return base64.b64decode(body)
    return urllib.parse.unquote_to_bytes(body)


def read_accessor(document: dict[str, Any], binary: bytes, accessor_index: int) -> np.ndarray:
    accessor = document["accessors"][accessor_index]
    view = document["bufferViews"][accessor["bufferView"]]
    dtype_name, component_size = COMPONENTS[accessor["componentType"]]
    component_count = TYPE_COUNTS[accessor["type"]]
    count = int(accessor["count"])
    stride = int(view.get("byteStride", component_count * component_size))
    start = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    dtype = np.dtype(dtype_name)
    if stride == component_count * component_size:
        array = np.frombuffer(binary, dtype=dtype, count=count * component_count, offset=start).reshape(count, component_count).copy()
    else:
        array = np.ndarray(
            shape=(count, component_count),
            dtype=dtype,
            buffer=memoryview(binary),
            offset=start,
            strides=(stride, component_size),
        ).copy()
    if accessor.get("normalized"):
        if accessor["componentType"] == 5121:
            array = array.astype(np.float32) / 255.0
        elif accessor["componentType"] == 5123:
            array = array.astype(np.float32) / 65535.0
        elif accessor["componentType"] == 5120:
            array = np.maximum(array.astype(np.float32) / 127.0, -1.0)
        elif accessor["componentType"] == 5122:
            array = np.maximum(array.astype(np.float32) / 32767.0, -1.0)
    return array


def quaternion_matrix(quaternion: list[float]) -> np.ndarray:
    x, y, z, w = (float(value) for value in quaternion)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0],
            [0, 0, 0, 1],
        ],
        dtype=np.float32,
    )


def node_matrix(node: dict[str, Any]) -> np.ndarray:
    if "matrix" in node:
        # glTF matrices are stored column-major.
        return np.asarray(node["matrix"], dtype=np.float32).reshape((4, 4), order="F")
    translation = np.eye(4, dtype=np.float32)
    translation[:3, 3] = np.asarray(node.get("translation", [0, 0, 0]), dtype=np.float32)
    scale = np.eye(4, dtype=np.float32)
    scale[0, 0], scale[1, 1], scale[2, 2] = node.get("scale", [1, 1, 1])
    return translation @ quaternion_matrix(node.get("rotation", [0, 0, 0, 1])) @ scale


def mesh_instances(document: dict[str, Any]) -> list[tuple[int, np.ndarray]]:
    instances: list[tuple[int, np.ndarray]] = []

    def visit(node_index: int, parent: np.ndarray) -> None:
        node = document["nodes"][node_index]
        world = parent @ node_matrix(node)
        if "mesh" in node:
            instances.append((int(node["mesh"]), world))
        for child in node.get("children", []):
            visit(int(child), world)

    scenes = document.get("scenes", [])
    scene_index = int(document.get("scene", 0)) if scenes else -1
    if 0 <= scene_index < len(scenes):
        for root in scenes[scene_index].get("nodes", []):
            visit(int(root), np.eye(4, dtype=np.float32))
    elif document.get("nodes"):
        children = {int(child) for node in document["nodes"] for child in node.get("children", [])}
        roots = [index for index in range(len(document["nodes"])) if index not in children]
        for root in roots:
            visit(root, np.eye(4, dtype=np.float32))
    if not instances:
        instances = [(index, np.eye(4, dtype=np.float32)) for index in range(len(document.get("meshes", [])))]
    return instances


def embedded_texture(document: dict[str, Any], material_index: int) -> tuple[np.ndarray, list[float]]:
    material = document.get("materials", [])[material_index] if document.get("materials") else {}
    pbr = material.get("pbrMetallicRoughness", {})
    factor = [float(value) for value in pbr.get("baseColorFactor", [1, 1, 1, 1])]
    texture_info = pbr.get("baseColorTexture")
    if texture_info is None:
        return np.full((1, 1, 4), 255, dtype=np.uint8), factor
    texture = document["textures"][int(texture_info["index"])]
    image = document["images"][int(texture["source"])]
    if not image.get("uri", "").startswith("data:"):
        raise ValueError("snapshot renderer requires an embedded image data URI")
    decoded = Image.open(io.BytesIO(data_uri_bytes(image["uri"]))).convert("RGBA")
    return np.asarray(decoded, dtype=np.uint8), factor


def snapshot_caption(document: dict[str, Any], source: Path, requested: str | None) -> str:
    if requested is not None:
        caption = " ".join(requested.split())
        if not caption:
            raise ValueError("snapshot title cannot be empty")
        return caption[:120]
    mesh_name = str(document.get("meshes", [{}])[0].get("name", "")).strip()
    label = mesh_name or source.stem
    return f"{label} / textured glTF"[:120]


def render(
    document: dict[str, Any],
    binary: bytes,
    width: int,
    height: int,
    caption: str,
) -> tuple[Image.Image, dict[str, Any]]:
    triangles: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[float]]] = []
    for mesh_index, transform in mesh_instances(document):
        mesh = document["meshes"][mesh_index]
        for primitive in mesh.get("primitives", []):
            if primitive.get("mode", 4) != 4:
                continue
            attributes = primitive.get("attributes", {})
            if "POSITION" not in attributes or "TEXCOORD_0" not in attributes:
                continue
            positions = read_accessor(document, binary, int(attributes["POSITION"])).astype(np.float32)
            normals = read_accessor(document, binary, int(attributes["NORMAL"])).astype(np.float32) if "NORMAL" in attributes else np.zeros_like(positions)
            uvs = read_accessor(document, binary, int(attributes["TEXCOORD_0"])).astype(np.float32)
            if "indices" in primitive:
                indices = read_accessor(document, binary, int(primitive["indices"])).reshape(-1).astype(np.int64)
            else:
                indices = np.arange(len(positions), dtype=np.int64)
            homogeneous = np.concatenate((positions, np.ones((len(positions), 1), dtype=np.float32)), axis=1)
            transformed = (transform @ homogeneous.T).T[:, :3]
            normal_matrix = transform[:3, :3]
            transformed_normals = (normal_matrix @ normals.T).T
            texture, factor = embedded_texture(document, int(primitive.get("material", 0)))
            for start in range(0, len(indices) - 2, 3):
                vertex_indices = indices[start : start + 3]
                triangles.append(
                    (
                        transformed[vertex_indices],
                        transformed_normals[vertex_indices],
                        uvs[vertex_indices],
                        texture,
                        np.asarray(factor, dtype=np.float32),
                        np.asarray(vertex_indices, dtype=np.int64),
                    )
                )
    if not triangles:
        raise ValueError("no textured triangle primitive found")

    all_points = np.concatenate([item[0] for item in triangles], axis=0)
    # A mild three-quarter turn makes depth and texture placement easier to inspect.
    yaw = math.radians(-18.0)
    pitch = math.radians(4.0)
    ry = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]], dtype=np.float32)
    rx = np.array([[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]], dtype=np.float32)
    view_rotation = rx @ ry
    rotated_points = (view_rotation @ all_points.T).T
    low, high = rotated_points.min(axis=0), rotated_points.max(axis=0)
    center = (low + high) * 0.5
    extent = max(float(high[0] - low[0]), float(high[1] - low[1]), 1e-6)
    scale = min((width - 72) / extent, (height - 84) / extent)

    # Deep blue-violet background with a subtle vertical gradient.
    pixels = np.zeros((height, width, 4), dtype=np.uint8)
    for row in range(height):
        t = row / max(height - 1, 1)
        pixels[row, :, :3] = (np.array([9, 13, 24]) * (1 - t) + np.array([32, 16, 42]) * t).astype(np.uint8)
        pixels[row, :, 3] = 255
    z_buffer = np.full((height, width), -np.inf, dtype=np.float32)
    light_direction = np.asarray([0.35, 0.65, 0.7], dtype=np.float32)
    light_direction /= np.linalg.norm(light_direction)

    for points, normals, uvs, texture, factor, _ in triangles:
        view_points = (view_rotation @ points.T).T
        view_normals = (view_rotation @ normals.T).T
        xy = np.empty((3, 2), dtype=np.float32)
        xy[:, 0] = (view_points[:, 0] - center[0]) * scale + width * 0.5
        xy[:, 1] = height * 0.5 - (view_points[:, 1] - center[1]) * scale
        min_x = max(0, int(math.floor(float(xy[:, 0].min()))))
        max_x = min(width - 1, int(math.ceil(float(xy[:, 0].max()))))
        min_y = max(0, int(math.floor(float(xy[:, 1].min()))))
        max_y = min(height - 1, int(math.ceil(float(xy[:, 1].max()))))
        if min_x > max_x or min_y > max_y:
            continue
        denominator = ((xy[1, 1] - xy[2, 1]) * (xy[0, 0] - xy[2, 0]) + (xy[2, 0] - xy[1, 0]) * (xy[0, 1] - xy[2, 1]))
        if abs(float(denominator)) < 1e-7:
            continue
        grid_x, grid_y = np.meshgrid(np.arange(min_x, max_x + 1, dtype=np.float32) + 0.5, np.arange(min_y, max_y + 1, dtype=np.float32) + 0.5)
        w0 = ((xy[1, 1] - xy[2, 1]) * (grid_x - xy[2, 0]) + (xy[2, 0] - xy[1, 0]) * (grid_y - xy[2, 1])) / denominator
        w1 = ((xy[2, 1] - xy[0, 1]) * (grid_x - xy[2, 0]) + (xy[0, 0] - xy[2, 0]) * (grid_y - xy[2, 1])) / denominator
        w2 = 1.0 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        depth = w0 * view_points[0, 2] + w1 * view_points[1, 2] + w2 * view_points[2, 2]
        z_slice = z_buffer[min_y : max_y + 1, min_x : max_x + 1]
        nearer = inside & (depth > z_slice)
        if not nearer.any():
            continue
        uv = w0[..., None] * uvs[0] + w1[..., None] * uvs[1] + w2[..., None] * uvs[2]
        tex_height, tex_width = texture.shape[:2]
        tex_u = np.mod(uv[..., 0], 1.0)
        # glTF UVs in this publication use the PNG's top-left image origin.
        # Flipping V here would put facial pixels on clothing/armor islands
        # (the previous diagnostic made the face appear corrupted).
        tex_v = np.mod(uv[..., 1], 1.0)
        tex_x = np.clip((tex_u * (tex_width - 1)).astype(np.int64), 0, tex_width - 1)
        tex_y = np.clip((tex_v * (tex_height - 1)).astype(np.int64), 0, tex_height - 1)
        sampled = texture[tex_y, tex_x].astype(np.float32)
        sampled[:, :, :3] *= factor[:3]
        sampled[:, :, 3] *= factor[3]
        normal = w0[..., None] * view_normals[0] + w1[..., None] * view_normals[1] + w2[..., None] * view_normals[2]
        normal /= np.maximum(np.linalg.norm(normal, axis=2, keepdims=True), 1e-6)
        shade = 0.42 + 0.58 * np.abs(np.sum(normal * light_direction, axis=2))
        sampled[:, :, :3] *= shade[..., None]
        visible = nearer & (sampled[:, :, 3] >= 8)
        if not visible.any():
            continue
        target = pixels[min_y : max_y + 1, min_x : max_x + 1]
        target[visible] = np.clip(sampled[visible], 0, 255).astype(np.uint8)
        z_slice[visible] = depth[visible]

    image = Image.fromarray(pixels, mode="RGBA")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 44), fill=(5, 8, 15, 235))
    try:
        font = ImageFont.truetype("segoeui.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    draw.text((16, 13), caption, fill=(218, 233, 247, 255), font=font)
    return image.convert("RGB"), {
        "triangles": len(triangles),
        "embedded_texture": True,
        "texture_size": [int(texture.shape[1]), int(texture.shape[0])],
        "projection": "orthographic software rasterizer",
        "texture_v_flip": False,
        "texture_coordinate_note": "glTF UV V is sampled in the PNG top-left image orientation",
        "caption": caption,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--title", help="display caption; defaults to the glTF mesh name or source filename")
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix(".json").exists():
        raise SystemExit("snapshot output already exists; use a new output path")
    document = json.loads(args.source.read_text(encoding="utf-8"))
    buffers = document.get("buffers", [])
    if not buffers or not buffers[0].get("uri", "").startswith("data:"):
        raise SystemExit("source glTF must contain an embedded buffer")
    binary = data_uri_bytes(buffers[0]["uri"])
    caption = snapshot_caption(document, args.source, args.title)
    image, report = render(document, binary, 768, 768, caption)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.output, format="PNG")
    source_hash = sha256_file(args.source)
    report.update({"source": str(args.source.resolve()), "source_sha256": source_hash, "output": str(args.output.resolve()), "source_bytes": args.source.stat().st_size, "output_bytes": args.output.stat().st_size})
    args.output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
