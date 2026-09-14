from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "programs" / "build_character_asset_manifest.py"
SPEC = importlib.util.spec_from_file_location("build_character_asset_manifest", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CharacterAssetManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_catalog(self) -> Path:
        model_output = self.root / "model.gltf"
        model_output.write_text('{"asset":{"version":"2.0"}}\n', encoding="utf-8")
        model_sha = hashlib.sha256(model_output.read_bytes()).hexdigest()
        texture_output = self.root / "texture.png"
        texture_output.write_bytes(b"not-an-image-fixture")
        texture_sha = hashlib.sha256(texture_output.read_bytes()).hexdigest()
        catalog = {
            "schema_version": 1,
            "stage": "textured-static-pilot",
            "status": "complete",
            "models": [
                {
                    "mesh_sha256": "a" * 64,
                    "mesh_logical_paths": ["model/s3_hairen/s3_hairen.mesh"],
                    "status": "converted",
                    "output": str(model_output),
                    "output_sha256": model_sha,
                    "materials": [
                        {
                            "ordinal": 0,
                            "name": "Material #0",
                            "tex0": "model\\s3_hairen\\s3_hairen.tga",
                            "technique": "shader/common.fx::TShader",
                            "texture_source_sha256": "b" * 64,
                            "texture_output_sha256": texture_sha,
                        }
                    ],
                },
                {
                    "mesh_sha256": "c" * 64,
                    "mesh_logical_paths": ["model/c1_hairen/c1_hairen.mesh"],
                    "status": "converted",
                    "output": str(model_output),
                    "output_sha256": model_sha,
                    "materials": [
                        {
                            "ordinal": 0,
                            "tex0": "model\\c1_hairen\\c1_hairen.tga",
                            "technique": "shader/common.fx::TShader",
                            "texture_source_sha256": "b" * 64,
                            "texture_output_sha256": texture_sha,
                        }
                    ],
                },
            ],
            "textures": [
                {
                    "output": str(texture_output),
                    "output_sha256": texture_sha,
                    "source_sha256": "b" * 64,
                }
            ],
        }
        path = self.root / "textured-static-manifest.json"
        path.write_text(json.dumps(catalog), encoding="utf-8")
        return path

    def write_table(self) -> Path:
        path = self.root / "characters.tsv"
        path.write_text(
            "character_id\tname_ja\tname_zh\treading\tasset_token\tsource_ref\n"
            "hairen\t海忍\t海忍\tかいにん\thairen\ttest\n",
            encoding="utf-8",
        )
        return path

    def write_evidence(self) -> Path:
        reference = self.root / "hairen-reference.png"
        reference.write_bytes(b"reference-image-fixture")
        reference_sha = hashlib.sha256(reference.read_bytes()).hexdigest()
        path = self.root / "evidence.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "character_id": "hairen",
                    "references": [
                        {
                            "reference_id": "hairen-s3-illustration",
                            "kind": "image",
                            "label": "Hairen S3 illustration",
                            "path": reference.name,
                            "sha256": reference_sha,
                        }
                    ],
                    "variants": [
                        {
                            "variant_id": "s3",
                            "logical_path": "model/s3_hairen/s3_hairen.mesh",
                            "status": "verified",
                            "confidence": "high",
                            "reference_ids": ["hairen-s3-illustration"],
                            "evidence_ref": "test-evidence#s3",
                            "evidence_note": "Reference illustration and textured render agree.",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_family_candidates_are_retained_and_exact_evidence_promotes_one(self) -> None:
        output = self.root / "run"
        manifest = MODULE.build_manifest(
            self.write_table(), [self.write_catalog()], output, self.write_evidence()
        )
        self.assertEqual(manifest["status"], "complete")
        character = manifest["characters"][0]
        self.assertEqual(character["candidate_count"], 2)
        self.assertEqual(character["verified_count"], 1)
        statuses = {item["logical_path"]: item["selection_status"] for item in character["model_candidates"]}
        self.assertEqual(statuses["model/s3_hairen/s3_hairen.mesh"], "verified")
        self.assertEqual(statuses["model/c1_hairen/c1_hairen.mesh"], "unmapped-candidate")
        publication = {item["logical_path"]: item["publication_status"] for item in character["model_candidates"]}
        self.assertEqual(publication["model/s3_hairen/s3_hairen.mesh"], "verified")
        self.assertEqual(publication["model/c1_hairen/c1_hairen.mesh"], "blocked-visual-evidence")
        verified = next(
            item for item in character["model_candidates"]
            if item["logical_path"] == "model/s3_hairen/s3_hairen.mesh"
        )
        self.assertEqual(verified["visual_reference_ids"], ["hairen-s3-illustration"])
        self.assertEqual(len(verified["visual_reference_sha256s"]), 1)
        self.assertEqual(manifest["counts"]["joined_models"], 2)
        self.assertEqual(len(manifest["unresolved"]), 1)
        self.assertTrue((output / "normalized-character-assets.tsv").is_file())
        self.assertTrue((output / "character-asset-manifest.json").is_file())

    def test_table_rejects_duplicate_ids(self) -> None:
        path = self.root / "duplicate.tsv"
        path.write_text(
            "character_id\tname_ja\tname_zh\treading\tasset_token\tsource_ref\n"
            "hairen\t海忍\t海忍\tかいにん\thairen\ttest\n"
            "hairen\t海忍\t海忍\tかいにん\thairen\ttest\n",
            encoding="utf-8",
        )
        with self.assertRaises(MODULE.CharacterManifestError):
            MODULE.load_character_table(path)

    def test_user_four_column_table_is_normalized_with_rarity_and_pinyin_key(self) -> None:
        path = self.root / "user-table.tsv"
        path.write_text(
            "rarity\tjapanese\tchinese\tpinyin\n"
            "SR\t海忍\t海忍\thairen\n",
            encoding="utf-8",
        )
        rows = MODULE.load_character_table(path)
        self.assertEqual(rows[0]["character_id"], "hairen")
        self.assertEqual(rows[0]["asset_token"], "hairen")
        self.assertEqual(rows[0]["rarity"], "SR")
        self.assertEqual(MODULE.character_table_columns(path), ("rarity", "japanese", "chinese", "pinyin"))

    def test_user_japanese_header_aliases_are_accepted(self) -> None:
        path = self.root / "user-table-ja.tsv"
        path.write_text(
            "レアリティ\t日本語\t中国語\t中国語読み\n"
            "SR\t海忍\t海忍\thairen\n",
            encoding="utf-8",
        )
        rows = MODULE.load_character_table(path)
        self.assertEqual(rows[0]["name_ja"], "海忍")
        self.assertEqual(rows[0]["reading"], "hairen")

    def test_existing_output_directory_is_not_overwritten(self) -> None:
        output = self.root / "run"
        output.mkdir()
        sentinel = output / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        with self.assertRaises(MODULE.CharacterManifestError):
            MODULE.build_manifest(self.write_table(), [self.write_catalog()], output)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_verified_variant_requires_sha_pinned_image_reference(self) -> None:
        evidence = self.root / "missing-reference.json"
        evidence.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "character_id": "hairen",
                    "references": [],
                    "variants": [
                        {
                            "variant_id": "s3",
                            "logical_path": "model/s3_hairen/s3_hairen.mesh",
                            "status": "verified",
                            "confidence": "high",
                            "evidence_ref": "test",
                            "evidence_note": "Visual comparison was claimed without an image.",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(MODULE.CharacterManifestError, "image reference"):
            MODULE.load_evidence(evidence)

    def test_local_reference_hash_must_match(self) -> None:
        reference = self.root / "reference.png"
        reference.write_bytes(b"reference")
        evidence = self.root / "bad-reference.json"
        evidence.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "character_id": "hairen",
                    "references": [
                        {
                            "reference_id": "hairen-image",
                            "kind": "image",
                            "path": reference.name,
                            "sha256": "0" * 64,
                        }
                    ],
                    "variants": [],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(MODULE.CharacterManifestError, "SHA-256"):
            MODULE.load_evidence(evidence)


if __name__ == "__main__":
    unittest.main()
