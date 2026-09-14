from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "programs" / "src"))

from asset_extractor.schema import (  # noqa: E402
    SCHEMA_NAMES,
    check_schema,
    validate_document,
)


JSONSCHEMA_AVAILABLE = importlib.util.find_spec("jsonschema") is not None


@unittest.skipUnless(JSONSCHEMA_AVAILABLE, "jsonschema is supplied by requirements-dev.txt")
class SchemaContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema_root = PROJECT_ROOT / "development" / "schemas"

    def test_all_repository_schemas_are_valid_draft_2020_12_documents(self) -> None:
        for name in SCHEMA_NAMES:
            with self.subTest(schema=name):
                check_schema(name, self.schema_root)

    def test_visual_reference_fixture_matches_its_schema(self) -> None:
        path = PROJECT_ROOT / "development" / "config" / "character-asset-evidence-20260914.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(validate_document(document, "visual-reference-evidence", self.schema_root), [])


if __name__ == "__main__":
    unittest.main()
