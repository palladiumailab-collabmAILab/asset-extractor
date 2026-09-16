"""Optional JSON-Schema contracts for generated manifests.

The extraction library deliberately keeps its runtime dependencies small.  The
``jsonschema`` package is therefore a development/CI dependency and is loaded
only when a caller explicitly asks for contract validation.  This module keeps
schema discovery and error formatting in one place so individual producers do
not each grow a subtly different validator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


SCHEMA_NAMES = (
    "asset-name-match",
    "backend-runs-manifest",
    "bluestacks-snapshot",
    "character-asset-manifest",
    "minimal-restore-test",
    "netease-backend-manifest",
    "pipeline-config",
    "pipeline-manifest",
    "run-manifest",
    "visual-reference-evidence",
)


class SchemaContractError(ValueError):
    """Raised when a schema cannot be loaded or an instance is invalid."""


def default_schema_root() -> Path:
    """Return the repository schema directory for a source checkout."""

    return Path(__file__).resolve().parents[3] / "development" / "schemas"


def schema_path(name: str, schema_root: Path | None = None) -> Path:
    """Resolve one allow-listed schema name without accepting path traversal."""

    if name not in SCHEMA_NAMES:
        raise SchemaContractError(f"unknown manifest schema: {name}")
    root = (schema_root or default_schema_root()).resolve()
    path = (root / f"{name}.schema.json").resolve()
    if path.parent != root:
        raise SchemaContractError(f"schema is outside schema root: {name}")
    return path


def load_schema(name: str, schema_root: Path | None = None) -> dict[str, Any]:
    """Load one JSON schema document."""

    path = schema_path(name, schema_root)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SchemaContractError(f"cannot read schema {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SchemaContractError(f"schema must be a JSON object: {path}")
    return value


def _jsonschema_validator(schema: dict[str, Any]) -> Any:
    """Construct the standard Draft 2020-12 validator on demand."""

    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:  # pragma: no cover - exercised in minimal installs
        raise SchemaContractError(
            "JSON-Schema validation requires jsonschema; install requirements-dev.txt"
        ) from exc
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_document(
    document: Any,
    name: str,
    schema_root: Path | None = None,
) -> list[str]:
    """Return deterministic, human-readable validation errors for a document."""

    validator = _jsonschema_validator(load_schema(name, schema_root))
    errors = validator.iter_errors(document)
    ordered = sorted(errors, key=lambda error: tuple(str(part) for part in error.absolute_path))
    return [f"{name}{_format_path(error.absolute_path)}: {error.message}" for error in ordered]


def check_schema(name: str, schema_root: Path | None = None) -> None:
    """Fail if one schema is malformed, without requiring an instance."""

    _jsonschema_validator(load_schema(name, schema_root))


def _format_path(parts: Iterable[Any]) -> str:
    path = ""
    for part in parts:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path or ".<root>"
