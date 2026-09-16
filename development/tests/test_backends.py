from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
from unittest.mock import patch



PROJECT_ROOT = Path(__file__).resolve().parents[2]

from asset_extractor.backends import (  # noqa: E402
    BackendRegistry,
    BackendRequest,
    BuiltinBackend,
    DedicatedBackend,
    extract_with_backend,
)
from asset_extractor.cli import build_parser  # noqa: E402
from asset_extractor.errors import ExtractionError  # noqa: E402


class BackendContractTests(unittest.TestCase):
    def test_registry_is_replaceable_without_changing_cli(self) -> None:
        class FakeBackend:
            name = "fake"

            def extract(self, request: BackendRequest) -> dict[str, object]:
                return {"status": "complete", "backend": self.name}

        registry = BackendRegistry()
        registry.register("fake", FakeBackend())
        result = extract_with_backend(
            BackendRequest(source_paths=(), output=Path("run"), backend="fake"),
            registry,
        )
        self.assertEqual(result, {"status": "complete", "backend": "fake"})

    def test_builtin_adapter_executes_existing_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sample.zip"
            output = root / "run"
            import zipfile

            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("asset.txt", b"fixture")
            manifest = BuiltinBackend().extract(
                BackendRequest(
                    source_paths=(source,),
                    output=output,
                    backend="builtin",
                    profile="zip",
                )
            )
            self.assertEqual(manifest["status"], "complete")

    def test_dedicated_adapter_reads_manifest_and_uses_argument_list(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "run"
            output.mkdir()
            (output / "backend-run-manifest.json").write_text(
                json.dumps({"status": "partial"}), encoding="utf-8"
            )
            source = root / "sample.npk"
            source.write_bytes(b"source")
            script = root / "wrapper.py"
            script.write_text("", encoding="utf-8")
            adapter = DedicatedBackend(script)
            request = BackendRequest(source_paths=(source,), output=output, backend="auto")
            with patch(
                "asset_extractor.backends.subprocess.run", return_value=CompletedProcess([], 1)
            ) as run:
                manifest = adapter.extract(request)
            self.assertEqual(manifest["status"], "partial")
            command = run.call_args.args[0]
            self.assertEqual(command[1], str(script.resolve()))
            self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_dedicated_adapter_converts_timeout_to_domain_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sample.npk"
            source.write_bytes(b"source")
            script = root / "wrapper.py"
            script.write_text("", encoding="utf-8")
            adapter = DedicatedBackend(script)
            adapter.timeout_seconds = 5
            request = BackendRequest(source_paths=(source,), output=root / "run", backend="auto")
            timeout = TimeoutExpired(
                ["python"], 5, output="partial stdout", stderr="partial stderr"
            )
            with patch("asset_extractor.backends.subprocess.run", side_effect=timeout):
                with self.assertRaises(ExtractionError) as caught:
                    adapter.extract(request)

        message = str(caught.exception)
        self.assertIn("backend=auto", message)
        self.assertIn(f"source={source.resolve()}", message)
        self.assertIn("timeout_seconds=5", message)
        self.assertIn("partial stdout", message)
        self.assertIn("partial stderr", message)

    def test_extract_cli_exposes_backend_selection(self) -> None:
        arguments = build_parser().parse_args(
            [
                "extract",
                "source.npk",
                "--output",
                "run",
                "--backend",
                "auto",
                "--game-profile",
                "onmyoji",
            ]
        )
        self.assertEqual(arguments.backend, "auto")
        self.assertEqual(arguments.game_profile, "onmyoji")


if __name__ == "__main__":
    unittest.main()
