from __future__ import annotations

import json
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "programs" / "src"))

from asset_extractor.cli import main  # noqa: E402
from asset_extractor.errors import ExtractionError  # noqa: E402
from asset_extractor.matcher import build_match_manifest, load_dictionary, path_tokens  # noqa: E402
from asset_extractor.schema import validate_document  # noqa: E402


JSONSCHEMA_AVAILABLE = importlib.util.find_spec("jsonschema") is not None


class AssetMatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_dictionary(self) -> Path:
        path = self.root / "characters.csv"
        path.write_text(
            "entity_id,entity_type,rarity,name_ja,name_zh,romanized,aliases\n"
            "hairen,character,SR,海忍,海忍,hairen,hai-ren|kainin\n"
            "yaodaoji,character,SSR,妖刀姫,妖刀姬,yaodaoji,\n",
            encoding="utf-8",
        )
        return path

    def test_variant_and_separator_tokens_are_normalized(self) -> None:
        tokens = path_tokens("model/s2_hai_ren/s2_hai_ren.mesh")
        self.assertIn(("normalized", "hairen"), tokens)
        self.assertNotIn(("exact", "hairen"), tokens)

    def test_same_named_model_and_illustration_are_paired(self) -> None:
        dictionary = self.write_dictionary()
        assets = self.root / "assets.json"
        assets.write_text(json.dumps({"assets": [
            {"asset_id": "mesh-1", "logical_path": "model/s2_hairen/s2_hairen.mesh", "asset_type": "mesh"},
            {"asset_id": "image-1", "logical_path": "illustration/hairen/hairen.png", "asset_type": "illustration"},
            {"asset_id": "unknown", "logical_path": "audio/other.ogg", "asset_type": "audio"},
        ]}), encoding="utf-8")
        manifest = build_match_manifest(dictionary, assets)
        self.assertEqual(manifest["summary"], {"assets": 3, "matched": 2, "unmatched": 1, "paired_3d_image": 2})
        mesh, image, unknown = manifest["matches"]
        self.assertEqual(mesh["match_method"], "normalized")
        self.assertEqual(mesh["entity"]["name_ja"], "海忍")
        self.assertEqual(image["match_method"], "exact")
        self.assertEqual(mesh["same_name_pair_status"], "paired-3d-image")
        self.assertEqual(mesh["same_name_peer_indices"], [1])
        self.assertEqual(unknown["match_method"], "unmatched")
        self.assertEqual(unknown["source_asset"]["asset_id"], "unknown")
        if JSONSCHEMA_AVAILABLE:
            self.assertEqual(
                validate_document(
                    manifest,
                    "asset-name-match",
                    PROJECT_ROOT / "development" / "schemas",
                ),
                [],
            )

    def test_alias_and_missing_logical_path_are_explicit(self) -> None:
        dictionary = self.write_dictionary()
        assets = self.root / "assets.json"
        assets.write_text(json.dumps({"entries": [
            {"logical_path": "portrait/kainin.png", "asset_type": "sprite"},
            {"logical_path": None, "path": None, "asset_type": "texture"},
        ]}), encoding="utf-8")
        manifest = build_match_manifest(dictionary, assets)
        self.assertEqual(manifest["matches"][0]["match_method"], "alias")
        self.assertEqual(manifest["matches"][1]["evidence"], "logical_path_missing")

    def test_dictionary_is_game_replaceable_json(self) -> None:
        dictionary = self.root / "entities.json"
        dictionary.write_text(json.dumps({"entities": [{
            "entity_id": "hero1", "entity_type": "character", "asset_token": "hero-one",
            "name_ja": "勇者", "aliases": ["h1"], "game_specific": "kept",
        }]}), encoding="utf-8")
        rows = load_dictionary(dictionary)
        self.assertEqual(rows[0]["metadata"], {"game_specific": "kept"})

    def test_ambiguous_dictionary_alias_is_rejected(self) -> None:
        dictionary = self.root / "bad.json"
        dictionary.write_text(json.dumps([{"entity_id": "a", "asset_token": "same"}, {"entity_id": "b", "asset_token": "same"}]), encoding="utf-8")
        with self.assertRaises(ExtractionError):
            load_dictionary(dictionary)

    def test_cli_writes_new_manifest_and_refuses_overwrite(self) -> None:
        dictionary = self.write_dictionary()
        assets = self.root / "assets.json"
        assets.write_text('{"assets": []}\n', encoding="utf-8")
        output = self.root / "matched.json"
        self.assertEqual(main(["match-assets", "--dictionary", str(dictionary), "--assets", str(assets), "--output", str(output)]), 0)
        self.assertTrue(output.is_file())
        self.assertEqual(main(["match-assets", "--dictionary", str(dictionary), "--assets", str(assets), "--output", str(output)]), 2)


if __name__ == "__main__":
    unittest.main()
