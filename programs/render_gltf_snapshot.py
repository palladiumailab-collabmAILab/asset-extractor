#!/usr/bin/env python3
"""Render a textured glTF snapshot through established scene libraries.

This command intentionally contains no mesh parser or software rasterizer. It
uses trimesh for glTF loading/validation and pyrender for off-screen OpenGL
rendering. Install ``requirements-vision.txt`` for this optional stage.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

from runtime_artifacts import sha256_file


def snapshot_caption(document: dict[str, Any], source: Path, requested: str | None) -> str:
    """Return a short caption without embedding a character-specific rule."""

    if requested is not None:
        caption = " ".join(requested.split())
        if not caption:
            raise ValueError("snapshot title must not be empty")
        return caption
    meshes = document.get("meshes")
    if isinstance(meshes, list) and meshes and isinstance(meshes[0], dict) and meshes[0].get("name"):
        return f"{meshes[0]['name']} / textured glTF"
    return f"{source.stem} / textured glTF"


def _load_scene(source: Path) -> tuple[Any, Any, dict[str, Any]]:
    try:
        if sys.platform != "win32" and not os.environ.get("DISPLAY"):
            os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
            import pyglet  # type: ignore[import-not-found]

            pyglet.options["headless"] = True
        import numpy as np  # type: ignore[import-not-found]
        import trimesh  # type: ignore[import-not-found]
        import pyrender  # type: ignore[import-not-found]
        from trimesh.exchange import gltf  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "vision rendering dependencies are missing; install requirements-vision.txt"
        ) from exc

    document = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("source glTF must contain a JSON object")
    gltf.validate(document)
    loaded = trimesh.load(source, force="scene")
    if not isinstance(loaded, trimesh.Scene):
        loaded = trimesh.Scene(loaded)
    if not loaded.geometry:
        raise ValueError("source glTF contains no geometry")
    bounds = loaded.bounds
    if bounds is None:
        raise ValueError("source glTF has no finite bounds")
    low, high = np.asarray(bounds[0], dtype=np.float64), np.asarray(bounds[1], dtype=np.float64)
    if not np.isfinite(low).all() or not np.isfinite(high).all():
        raise ValueError("source glTF bounds are not finite")
    center = (low + high) * 0.5
    extent = float(np.max(high - low))
    if extent <= 0:
        raise ValueError("source glTF has zero-sized geometry")
    loaded.apply_translation(-center)

    render_scene = pyrender.Scene.from_trimesh_scene(
        loaded,
        bg_color=np.asarray([9, 13, 24, 255], dtype=np.uint8),
        ambient_light=np.asarray([0.18, 0.18, 0.18]),
    )
    camera = pyrender.PerspectiveCamera(yfov=math.radians(45.0), aspectRatio=1.0)
    distance = extent / (2.0 * math.tan(math.radians(45.0) / 2.0)) * 1.35
    camera_pose = np.eye(4, dtype=np.float64)
    camera_pose[:3, 3] = [0.0, 0.0, distance]
    render_scene.add(camera, pose=camera_pose)
    light = pyrender.DirectionalLight(color=np.ones(3), intensity=3.0)
    render_scene.add(light, pose=camera_pose)
    return render_scene, pyrender, {
        "projection": "pyrender perspective camera",
        "geometry_count": len(loaded.geometry),
        "extent": extent,
    }


def render_snapshot(source: Path, width: int = 768, height: int = 768) -> tuple[Any, dict[str, Any]]:
    """Render one glTF and return an RGB array plus provenance."""

    import numpy as np  # type: ignore[import-not-found]

    scene, pyrender, report = _load_scene(source)
    renderer = pyrender.OffscreenRenderer(viewport_width=width, viewport_height=height)
    try:
        color, _depth = renderer.render(scene)
    finally:
        renderer.delete()
    return np.asarray(color)[:, :, :3], {**report, "width": width, "height": height}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--title", help="retained for CLI compatibility and provenance")
    args = parser.parse_args(argv)
    source = args.source.resolve()
    output = args.output.resolve()
    report_path = output.with_suffix(".json")
    if output.exists() or report_path.exists():
        raise SystemExit("snapshot output already exists; use a new output path")
    document = json.loads(source.read_text(encoding="utf-8"))
    caption = snapshot_caption(document, source, args.title)
    try:
        image, report = render_snapshot(source)
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"glTF rendering failed: {exc}") from exc
    from PIL import Image

    output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image, mode="RGB").save(output, format="PNG")
    report.update(
        {
            "caption": caption,
            "source": str(source),
            "source_sha256": sha256_file(source),
            "output": str(output),
            "output_bytes": output.stat().st_size,
            "renderer": "pyrender",
        }
    )
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
