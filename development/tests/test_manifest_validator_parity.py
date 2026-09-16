from __future__ import annotations

import copy
import tempfile
import unittest
import zipfile
from pathlib import Path

from asset_extractor import manifest_validation as minimal_validator
from asset_extractor.manifest import validate_manifest
from asset_extractor.pipeline import extract_inputs
from asset_extractor.schema import load_schema, validate_document


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = PROJECT_ROOT / "development" / "schemas"


class ManifestValidatorParityTests(unittest.TestCase):
    def test_run_manifest_field_sets_match_dependency_free_validator(self) -> None:
        schema = load_schema("run-manifest", SCHEMA_ROOT)
        definitions = schema["$defs"]
        contracts = (
            (schema, minimal_validator._TOP_LEVEL_KEYS, set()),
            (definitions["input"], minimal_validator._INPUT_KEYS, set()),
            (definitions["outputs"], minimal_validator._OUTPUT_KEYS, set()),
            (definitions["file"], minimal_validator._FILE_KEYS, set()),
            (
                definitions["entry"],
                minimal_validator._ENTRY_KEYS,
                minimal_validator._ENTRY_OPTIONAL_KEYS,
            ),
            (definitions["failure"], minimal_validator._FAILURE_KEYS, set()),
            (definitions["claim"], minimal_validator._CLAIM_KEYS, set()),
            (definitions["scanEntry"], minimal_validator._SCAN_ENTRY_KEYS, set()),
        )

        for contract, required, optional in contracts:
            with self.subTest(title=contract.get("title", "nested contract")):
                self.assertEqual(set(contract["required"]), required)
                self.assertEqual(set(contract["properties"]), required | optional)

    def test_representative_valid_and_invalid_manifests_agree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "sample.zip"
            with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("asset.bin", b"payload")

            manifest = extract_inputs([str(source)], root / "run")
            self.assertEqual(validate_manifest(manifest), [])
            self.assertEqual(validate_document(manifest, "run-manifest", SCHEMA_ROOT), [])

            invalid_documents = []

            unexpected_top_level = copy.deepcopy(manifest)
            unexpected_top_level["unexpected"] = True
            invalid_documents.append(unexpected_top_level)

            invalid_status = copy.deepcopy(manifest)
            invalid_status["status"] = "unknown"
            invalid_documents.append(invalid_status)

            missing_output_field = copy.deepcopy(manifest)
            del missing_output_field["outputs"]["committed"]
            invalid_documents.append(missing_output_field)

            invalid_entry_sha = copy.deepcopy(manifest)
            invalid_entry_sha["entries"][0]["sha256"] = "not-a-sha256"
            invalid_documents.append(invalid_entry_sha)

            unexpected_entry_field = copy.deepcopy(manifest)
            unexpected_entry_field["entries"][0]["unexpected"] = "drift"
            invalid_documents.append(unexpected_entry_field)

            for document in invalid_documents:
                with self.subTest(document=document):
                    self.assertTrue(validate_manifest(document))
                    self.assertTrue(validate_document(document, "run-manifest", SCHEMA_ROOT))


if __name__ == "__main__":
    unittest.main()
