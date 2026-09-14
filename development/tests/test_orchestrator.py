from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "programs" / "src"))

from asset_extractor.orchestrator import PipelineError, run_pipeline  # noqa: E402
from asset_extractor.orchestrator import _source_paths  # noqa: E402
from asset_extractor.schema import validate_document  # noqa: E402
from asset_extractor.common import sha256_file  # noqa: E402


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class OrchestratorTests(unittest.TestCase):
    def test_acquisition_paths_are_resolved_and_verified_inside_snapshot_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "run"
            acquisition_root = output / "acquisition"
            payload = acquisition_root / "raw" / "optionres" / "asset.nxpk"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"NXPK-test")
            snapshot = {
                "status": "complete",
                "files": [
                    {
                        "local_path": "raw/optionres/asset.nxpk",
                        "bytes": payload.stat().st_size,
                        "sha256": sha256_file(payload),
                    }
                ],
            }
            (acquisition_root / "snapshot-manifest.json").parent.mkdir(parents=True, exist_ok=True)
            (acquisition_root / "snapshot-manifest.json").write_text(
                json.dumps(snapshot), encoding="utf-8"
            )
            completed = subprocess.CompletedProcess([], 0, "", "")
            with patch("asset_extractor.orchestrator._run_python", return_value=completed):
                paths, result = _source_paths({"acquisition": {}}, root, output)

        self.assertEqual(paths, [payload.resolve()])
        self.assertEqual(result["status"], "complete")

    def test_pipeline_extracts_classifies_and_pairs_same_named_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("model/s3_hairen/s3_hairen.mesh", b"\x34\x80\xc8\xbbmesh")
                archive.writestr("model/s3_hairen/s3_hairen.png", ONE_PIXEL_PNG)
                archive.writestr("movie/s3_hairen.mp4", b"....ftypisom")
            dictionary = root / "dictionary.json"
            dictionary.write_text(
                json.dumps({"entities": [{"entity_id": "hairen", "asset_token": "s3_hairen"}]}),
                encoding="utf-8",
            )
            config = root / "pipeline.json"
            config.write_text(
                json.dumps({"sources": ["source.zip"], "dictionary": "dictionary.json"}),
                encoding="utf-8",
            )
            output = root / "run"
            manifest = run_pipeline(config, output)

            self.assertEqual(manifest["status"], "partial")
            self.assertEqual(manifest["stages"]["extraction"]["status"], "complete")
            self.assertEqual(manifest["stages"]["classification"]["status"], "complete")
            self.assertEqual(manifest["stages"]["matching"]["summary"]["paired_3d_image"], 2)
            self.assertTrue((output / "pipeline-manifest.json").is_file())
            self.assertEqual(
                validate_document(
                    manifest,
                    "pipeline-manifest",
                    PROJECT_ROOT / "development" / "schemas",
                ),
                [],
            )

    def test_pipeline_does_not_overwrite_a_previous_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "pipeline.json"
            config.write_text(json.dumps({"sources": ["missing.zip"]}), encoding="utf-8")
            output = root / "run"
            output.mkdir()
            with self.assertRaises(PipelineError):
                run_pipeline(config, output)


if __name__ == "__main__":
    unittest.main()
