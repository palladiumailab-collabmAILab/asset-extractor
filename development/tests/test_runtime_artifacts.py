from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "programs"))

from runtime_artifacts import (  # noqa: E402
    canonical_json,
    digest_file,
    json_bytes,
    sha256_bytes,
    sha256_file,
    sha256_json,
    utc_now,
    write_bytes_atomic,
    write_json_atomic,
)


class RuntimeArtifactTests(unittest.TestCase):
    def test_hash_helpers_share_one_file_read_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "payload.bin"
            payload = b"asset-extractor"
            path.write_bytes(payload)
            expected = hashlib.sha256(payload).hexdigest()
            self.assertEqual(digest_file(path), (expected, len(payload)))
            self.assertEqual(sha256_file(path), expected)
            self.assertEqual(sha256_bytes(payload), expected)

    def test_json_hash_is_key_order_independent_and_artifact_is_readable(self) -> None:
        left = {"b": 2, "a": 1}
        right = {"a": 1, "b": 2}
        self.assertEqual(sha256_json(left), sha256_json(right))
        self.assertEqual(canonical_json(left), b'{"a":1,"b":2}')
        self.assertEqual(json.loads(json_bytes(left)), left)

    def test_atomic_writer_removes_partial_when_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "manifest.json"
            with patch("runtime_artifacts.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    write_json_atomic(target, {"status": "complete"})
            self.assertFalse(target.exists())
            self.assertEqual(list(root.glob(".manifest.json.*.partial")), [])

    def test_no_overwrite_contract_rejects_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "manifest.json"
            target.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                write_bytes_atomic(target, b"replace", overwrite=False)
            self.assertEqual(target.read_text(encoding="utf-8"), "keep")

    def test_utc_now_uses_explicit_utc_marker(self) -> None:
        self.assertTrue(utc_now().endswith("Z"))


if __name__ == "__main__":
    unittest.main()
