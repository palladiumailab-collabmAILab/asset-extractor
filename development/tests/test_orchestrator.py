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

from asset_extractor.classification import classify_manifest_entries  # noqa: E402
from asset_extractor.errors import ExtractionError  # noqa: E402
from asset_extractor.orchestrator import (  # noqa: E402
    PipelineError,
    _extract_sources,
    _run_python,
    _run_visual_stage,
    run_pipeline,
)
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

            self.assertEqual(manifest["status"], "complete")
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

    def test_minimal_pipeline_skips_optional_stages_without_degrading_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("asset.txt", b"fixture")
            config = root / "pipeline.json"
            config.write_text(json.dumps({"sources": ["source.zip"]}), encoding="utf-8")
            output = root / "run"

            manifest = run_pipeline(config, output)

        self.assertEqual(manifest["status"], "complete")
        for name in ("matching", "textured", "rendering", "visual"):
            self.assertEqual(manifest["stages"][name]["status"], "skipped")
            self.assertFalse(manifest["stages"][name]["required"])
        for name in ("acquisition", "extraction", "classification"):
            self.assertTrue(manifest["stages"][name]["required"])

    def test_extraction_failure_blocks_configured_downstream_stages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.npk"
            source.write_bytes(b"NXPK-fixture")
            config = root / "pipeline.json"
            config.write_text(
                json.dumps(
                    {
                        "sources": ["source.npk"],
                        "dictionary": "dictionary.json",
                        "textured": {"source_tree": "source-tree"},
                        "references": ["reference.png"],
                    }
                ),
                encoding="utf-8",
            )
            output = root / "run"
            with patch(
                "asset_extractor.orchestrator._extract_sources",
                side_effect=ExtractionError("dedicated backend timed out"),
            ):
                manifest = run_pipeline(config, output)

            persisted = json.loads((output / "pipeline-manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(persisted["status"], "failed")
        self.assertEqual(manifest["stages"]["extraction"]["status"], "failed")
        for name in ("classification", "matching", "textured", "rendering", "visual"):
            self.assertEqual(manifest["stages"][name]["status"], "blocked")
            self.assertTrue(manifest["stages"][name]["required"])

    def test_pipeline_does_not_overwrite_a_previous_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "pipeline.json"
            config.write_text(json.dumps({"sources": ["missing.zip"]}), encoding="utf-8")
            output = root / "run"
            output.mkdir()
            with self.assertRaises(PipelineError):
                run_pipeline(config, output)

    def test_pipeline_rejects_unknown_configuration_keys_before_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "pipeline.json"
            config.write_text(json.dumps({"sorces": ["input.zip"]}), encoding="utf-8")
            output = root / "run"
            with self.assertRaises(PipelineError):
                run_pipeline(config, output)
            self.assertFalse(output.exists())

    def test_pipeline_subprocesses_have_a_bounded_timeout(self) -> None:
        with patch(
            "asset_extractor.orchestrator.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["python"], 900),
        ):
            with self.assertRaises(PipelineError):
                _run_python(Path("stage.py"), [])

    def test_visual_stage_keeps_low_confidence_scores_partial(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "reference.png"
            candidate = root / "candidate.png"
            reference.write_bytes(ONE_PIXEL_PNG)
            candidate.write_bytes(ONE_PIXEL_PNG)
            low_confidence = {
                "status": "scored",
                "score": 1.0,
                "accepted": False,
                "confidence": "low",
            }
            with patch(
                "asset_extractor.orchestrator.compare_images",
                return_value=low_confidence,
            ):
                result = _run_visual_stage([str(reference)], root, [candidate])
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(result["results"][0]["accepted"])

    def test_dedicated_backend_collection_is_classifiable_with_its_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = [root / "first.npk", root / "second.npk"]
            for source in sources:
                source.write_bytes(b"NXPK" + source.name.encode("ascii"))
            extraction_root = root / "run" / "extraction"

            def fake_extract(request, _registry=None):
                request.output.mkdir(parents=True, exist_ok=True)
                payload = request.output / "raw" / "asset.png"
                payload.parent.mkdir(parents=True, exist_ok=True)
                payload.write_bytes(ONE_PIXEL_PNG)
                source_sha = sha256_file(request.source_paths[0])
                manifest = {
                    "schema_version": 1,
                    "operation": "extract-netease-backend",
                    "status": "complete",
                    "source": {
                        "sha256_before": source_sha,
                        "sha256_after": source_sha,
                        "unchanged": True,
                    },
                    "entries": [
                        {
                            "entry_index": 0,
                            "payload_id": 7,
                            "payload_offset": 64,
                            "output_path": "raw/asset.png",
                            "output_sha256": sha256_file(payload),
                            "bytes": payload.stat().st_size,
                            "status": "extracted",
                            "logical_path": "model/s3_hairen/s3_hairen.png",
                        }
                    ],
                    "failures": [],
                }
                (request.output / "backend-run-manifest.json").write_text(
                    json.dumps(manifest), encoding="utf-8"
                )
                return manifest

            config = {"backend": "neoxtractor", "profile": "auto"}
            with patch(
                "asset_extractor.orchestrator.extract_with_backend", side_effect=fake_extract
            ):
                extraction = _extract_sources(config, root, sources, extraction_root)

            self.assertEqual(extraction["operation"], "extract-backend-collection")
            self.assertTrue((extraction_root / "backend-runs-manifest.json").is_file())
            self.assertEqual(extraction["entries"][0]["source_input_index"], 0)
            self.assertEqual(
                validate_document(
                    extraction,
                    "backend-runs-manifest",
                    PROJECT_ROOT / "development" / "schemas",
                ),
                [],
            )
            classified = classify_manifest_entries(
                run_root=root / "run",
                source_manifest=extraction,
                output_manifest=root / "run" / "type-classification.json",
                raw_manifest=root / "run" / "raw-extraction-manifest.json",
                source_output_root=extraction_root,
            )
            self.assertEqual(classified["status"], "complete")
            self.assertEqual(classified["counts"]["image"], 2)


if __name__ == "__main__":
    unittest.main()
