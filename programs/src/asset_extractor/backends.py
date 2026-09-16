"""Backend contracts and adapters for extraction use cases."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

from .errors import ExtractionError
from .pipeline import extract_inputs


@dataclass(frozen=True)
class BackendRequest:
    """Immutable request shared by builtin and dedicated extraction adapters."""

    source_paths: tuple[Path, ...]
    output: Path
    backend: str
    game_profile: str = "onmyoji"
    profile: str = "auto"
    strict: bool = True
    limits: Mapping[str, int | float] = field(default_factory=dict)
    resume: bool = False
    neoxtractor_root: Path | None = None
    neoxtractor_config: Path | None = None
    neox_tools_root: Path | None = None
    backend_python: Path | None = None


class ExtractorBackend(Protocol):
    """Small extension point for a backend that can execute one request."""

    name: str

    def extract(self, request: BackendRequest) -> dict[str, Any]:
        """Execute the request and return a normalized manifest."""


class BackendRegistry:
    """Name-to-backend registry that can be extended by applications/tests."""

    def __init__(self, backends: Mapping[str, ExtractorBackend] | None = None) -> None:
        self._backends: dict[str, ExtractorBackend] = dict(backends or {})

    def register(self, name: str, backend: ExtractorBackend) -> None:
        normalized = name.strip().casefold()
        if not normalized:
            raise ValueError("backend name must not be empty")
        if normalized in self._backends:
            raise ValueError(f"backend is already registered: {name}")
        self._backends[normalized] = backend

    def resolve(self, name: str) -> ExtractorBackend:
        try:
            return self._backends[name.casefold()]
        except KeyError as exc:
            raise ExtractionError(f"unsupported extraction backend: {name}") from exc


class BuiltinBackend:
    """Adapter around the maintained standard-library extraction pipeline."""

    name = "builtin"

    def extract(self, request: BackendRequest) -> dict[str, Any]:
        return extract_inputs(
            [str(path) for path in request.source_paths],
            request.output,
            profile=request.profile,
            strict=request.strict,
            limits=dict(request.limits),
            resume=request.resume,
        )


class DedicatedBackend:
    """Process-isolated adapter for the NetEase/NeoX wrapper."""

    name = "netease-wrapper"
    timeout_seconds = 30 * 60

    def __init__(self, script_path: Path | None = None) -> None:
        self.script_path = (
            script_path or Path(__file__).resolve().parents[2] / "run_netease_backend.py"
        ).resolve()

    def _command(self, request: BackendRequest) -> list[str]:
        if len(request.source_paths) != 1:
            raise ExtractionError("dedicated backends currently accept exactly one input")
        if request.profile != "auto" or not request.strict or request.resume or request.limits:
            raise ExtractionError(
                "dedicated backends currently require profile=auto, strict extraction, "
                "default limits, and no --resume"
            )
        if not self.script_path.is_file():
            raise ExtractionError(f"dedicated backend wrapper is missing: {self.script_path}")
        command = [
            str(Path(sys.executable).resolve()),
            str(self.script_path),
            str(request.source_paths[0]),
            "--output",
            str(request.output),
            "--backend",
            request.backend,
            "--game-profile",
            request.game_profile,
        ]
        optional = (
            ("--neoxtractor-root", request.neoxtractor_root),
            ("--neoxtractor-config", request.neoxtractor_config),
            ("--neox-tools-root", request.neox_tools_root),
            ("--backend-python", request.backend_python),
        )
        for option, value in optional:
            if value is not None:
                command.extend((option, str(value)))
        return command

    def extract(self, request: BackendRequest) -> dict[str, Any]:
        command = self._command(request)
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:

            def bounded(value: str | bytes | None) -> str:
                if value is None:
                    return ""
                if isinstance(value, bytes):
                    value = value.decode("utf-8", errors="replace")
                return value.strip()[:500]

            source = str(request.source_paths[0].resolve())
            raise ExtractionError(
                "dedicated backend timed out: "
                f"backend={request.backend} source={source} "
                f"timeout_seconds={self.timeout_seconds} "
                f"stdout={bounded(exc.stdout)!r} stderr={bounded(exc.stderr)!r}"
            ) from exc
        for filename in ("backend-run-manifest.json", "run-manifest.json"):
            manifest_path = request.output / filename
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ExtractionError(
                    f"dedicated backend wrote an invalid manifest: {manifest_path}"
                ) from exc
            if not isinstance(manifest, dict):
                raise ExtractionError(
                    f"dedicated backend manifest must be an object: {manifest_path}"
                )
            if completed.returncode != 0 and manifest.get("status") == "complete":
                raise ExtractionError(
                    "dedicated backend exit code disagrees with complete manifest"
                )
            return manifest
        detail = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"exit code {completed.returncode}"
        )
        raise ExtractionError(f"dedicated backend produced no manifest: {detail}")


def default_backend_registry() -> BackendRegistry:
    dedicated = DedicatedBackend()
    return BackendRegistry(
        {
            "builtin": BuiltinBackend(),
            "auto": dedicated,
            "neoxtractor": dedicated,
            "neox-tools": dedicated,
        }
    )


def extract_with_backend(
    request: BackendRequest, registry: BackendRegistry | None = None
) -> dict[str, Any]:
    """Resolve a backend and execute it without exposing adapter internals to the CLI."""

    return (registry or default_backend_registry()).resolve(request.backend).extract(request)
