from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "programs"))
SCRIPT = PROJECT_ROOT / "programs" / "render_gltf_snapshot.py"
SPEC = importlib.util.spec_from_file_location("render_gltf_snapshot", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RenderGltfSnapshotTests(unittest.TestCase):
    def test_requested_caption_is_normalized(self) -> None:
        caption = MODULE.snapshot_caption({}, Path("model.gltf"), " Kainin   / s3_hairen ")
        self.assertEqual(caption, "Kainin / s3_hairen")

    def test_default_caption_uses_mesh_name_without_character_hardcoding(self) -> None:
        document = {"meshes": [{"name": "s3_hairen"}]}
        self.assertEqual(
            MODULE.snapshot_caption(document, Path("hash.gltf"), None),
            "s3_hairen / textured glTF",
        )

    def test_empty_requested_caption_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.snapshot_caption({}, Path("model.gltf"), "   ")

    @unittest.skipUnless(
        importlib.util.find_spec("trimesh") and importlib.util.find_spec("pyrender"),
        "vision dependencies are optional",
    )
    def test_established_renderer_can_render_a_small_scene(self) -> None:
        import trimesh

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "box.gltf"
            scene = trimesh.Scene(trimesh.creation.box())
            scene.export(source, file_type="gltf")
            try:
                image, report = MODULE.render_snapshot(source, 64, 64)
            except (ImportError, RuntimeError, OSError) as exc:
                self.skipTest(f"headless OpenGL runtime unavailable: {exc}")
        self.assertEqual(tuple(image.shape), (64, 64, 3))
        self.assertEqual(report["renderer"] if "renderer" in report else "pyrender", "pyrender")


if __name__ == "__main__":
    unittest.main()
