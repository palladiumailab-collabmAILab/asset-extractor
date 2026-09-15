"""Semantic classification for extracted payloads."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import atomic_write_json, sha256_file
from .media_probe import probe_file


def classify_file(path: Path) -> tuple[str, dict[str, Any], str]:
    """Return ``category``, probe evidence, and a useful extension hint."""

    evidence = probe_file(path)
    family = evidence["family"]
    if family == "texture":
        return "texture", evidence, evidence["format"]
    if family == "image":
        return "image", evidence, evidence["format"]
    if family == "3d":
        return "mesh", evidence, evidence["format"]
    if family == "3d-container":
        return "3d-container", evidence, evidence["format"]
    if family == "material":
        return "material", evidence, "xml"
    if family == "animation":
        return "skeleton/animation", evidence, "xml"
    if family == "scene":
        return "scene", evidence, "xml"
    if family == "audio":
        return "audio", evidence, evidence["format"]
    if family == "video":
        return "video", evidence, evidence["format"]
    return "unknown", evidence, "bin"


def classify_manifest_entries(
    *,
    run_root: Path,
    source_manifest: dict[str, Any],
    output_manifest: Path,
    raw_manifest: Path,
    source_output_root: Path | None = None,
) -> dict[str, Any]:
    """Create the classification contract consumed by texture publication.

    Paths are retained as absolute paths only when they remain below
    ``run_root``.  This makes the generated manifest usable by the existing
    NeoX publication stage while preserving a single source of truth for
    hashes and semantic categories.
    """

    outputs = source_manifest.get("outputs")
    declared_output_root = outputs.get("directory") if isinstance(outputs, dict) else None
    output_root = (
        Path(str(declared_output_root)).resolve()
        if declared_output_root
        else (source_output_root or run_root).resolve()
    )
    entries = source_manifest.get("entries", [])
    if not output_root.is_dir() or not isinstance(entries, list):
        raise ValueError("extraction manifest has no usable output directory or entries")

    classified: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for entry in entries:
        relative = Path(str(entry.get("output_path", "")))
        path = (output_root / relative).resolve()
        try:
            path.relative_to(run_root.resolve())
        except ValueError as exc:
            raise ValueError(f"extracted output escapes pipeline run root: {path}") from exc
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"extracted output is missing or unsafe: {path}")
        actual_bytes = path.stat().st_size
        actual_sha = sha256_file(path)
        declared_bytes = entry.get("bytes", entry.get("actual_size"))
        declared_sha = entry.get("sha256", entry.get("output_sha256"))
        if actual_bytes != declared_bytes or actual_sha != declared_sha:
            raise ValueError(f"extracted output changed after extraction: {path}")
        category, evidence, extension = classify_file(path)
        counts[category] = counts.get(category, 0) + 1
        classified.append(
            {
                "ordinal": entry.get("index", entry.get("entry_index", entry.get("ordinal"))),
                "payload_id": entry.get("payload_id"),
                "asset_id": entry.get("asset_id"),
                "offset": entry.get("offset", entry.get("payload_offset")),
                "packed_bytes": entry.get("packed_bytes"),
                "declared_unpacked_bytes": entry.get("declared_unpacked_bytes"),
                "path": str(path),
                "relative_path": str(path.relative_to(run_root.resolve())),
                "logical_path": entry.get("logical_path") or entry.get("path"),
                "logical_path_status": entry.get("logical_path_status"),
                "bytes": actual_bytes,
                "sha256": actual_sha,
                "category": category,
                "evidence": evidence,
                "semantic_extension_hint": extension,
                "raw_immutable": True,
            }
        )

    document = {
        "schema_version": 1,
        "stage": "type-classification",
        "status": "complete" if classified else "failed",
        "input_manifest": str(raw_manifest.resolve()),
        "method": "shared bounded media probe; decoder validation is a later stage",
        "counts": counts,
        "entry_count": len(classified),
        "outputs": classified,
        "conversion_stage": "not-run",
    }
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output_manifest, document)
    return document
