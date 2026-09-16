#!/usr/bin/env python3
"""Join a Japanese/Chinese character table to an existing textured catalog.

This is a small, read-only publication layer.  It does not inspect or rewrite
NPK payloads and it never guesses a material or texture relationship.  The
catalog is expected to be produced by ``prepare_textured_pilot.py`` (or an
equivalent resolver) and therefore already contains the evidence-backed
mesh/material/Tex0 links.  Character names are joined to logical mesh paths
only through an explicit, ASCII ``asset_token`` column.  When a family has
several variants, every candidate is retained; an optional evidence map may
promote exact logical paths to verified variants.

The maintained six-column table (``character_id`` … ``source_ref``) remains
supported.  The four-column table supplied for this task
(``rarity``, ``japanese``, ``chinese``, ``pinyin``; Japanese header aliases are
also accepted) is normalized to the same internal representation, preserving
rarity and using the pinyin as both the character id and asset token.  The
normalized legacy ``reading`` field mirrors pinyin for compatibility; the
explicit ``pinyin`` field identifies its actual meaning.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from runtime_artifacts import json_bytes, sha256_file, utc_now, write_bytes_atomic


SIX_COLUMN_TABLE_COLUMNS = (
    "character_id",
    "name_ja",
    "name_zh",
    "reading",
    "asset_token",
    "source_ref",
)
TABLE_COLUMNS = SIX_COLUMN_TABLE_COLUMNS
USER_TABLE_COLUMNS = ("rarity", "japanese", "chinese", "pinyin")
FOUR_COLUMN_TABLE_COLUMNS = USER_TABLE_COLUMNS
USER_TABLE_HEADER_ALIASES = {
    "rarity": "rarity",
    "レアリティ": "rarity",
    "japanese": "japanese",
    "日本語": "japanese",
    "name_ja": "japanese",
    "chinese": "chinese",
    "中国語": "chinese",
    "name_zh": "chinese",
    "pinyin": "pinyin",
    "中国語読み": "pinyin",
    "reading": "pinyin",
}
ALLOWED_RARITIES = {"UR", "SP", "SSR", "SR", "R", "N"}
TSV_COLUMNS = (
    "rarity",
    "character_id",
    "name_ja",
    "name_zh",
    "reading",
    "pinyin",
    "asset_token",
    "variant_id",
    "selection_status",
    "publication_status",
    "confidence",
    "logical_path",
    "mesh_sha256",
    "model_status",
    "join_status",
    "model_output_sha256",
    "model_output_verified",
    "material_count",
    "texture_output_sha256s",
    "visual_reference_ids",
    "visual_reference_sha256s",
    "evidence_ref",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
REFERENCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
ALLOWED_VARIANT_STATUS = {"verified", "auxiliary", "candidate", "unresolved"}
ALLOWED_REFERENCE_KINDS = {"image", "webpage", "document"}


class CharacterManifestError(ValueError):
    """Raised when an input table/catalog cannot be joined safely."""


def normalized_text(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value or "").strip())


def normalized_logical_path(value: Any) -> str:
    return normalized_text(value).replace("\\", "/").lower()


def ensure_no_control(value: str, field: str, line: int) -> str:
    if any(char in value for char in ("\t", "\r", "\n")):
        raise CharacterManifestError(f"line {line}: {field} contains a tab/newline")
    return value


def _header_kind(fields: Iterable[str]) -> tuple[str, tuple[str, ...]]:
    """Recognize the maintained six-column or user four-column table."""

    values = tuple(normalized_text(value).lower() for value in fields)
    if values == TABLE_COLUMNS:
        return "maintained", TABLE_COLUMNS
    if len(values) == len(USER_TABLE_COLUMNS):
        mapped = tuple(USER_TABLE_HEADER_ALIASES.get(value, "") for value in values)
        if set(mapped) == set(USER_TABLE_COLUMNS) and len(set(mapped)) == len(USER_TABLE_COLUMNS):
            return "user", mapped
    raise CharacterManifestError(
        "character table columns must be the maintained six-column form "
        f"{list(TABLE_COLUMNS)!r} or the four-column form "
        f"{list(USER_TABLE_COLUMNS)!r}; got {list(fields)!r}"
    )


def character_table_columns(path: Path) -> tuple[str, ...]:
    """Return the original header columns for manifest provenance."""

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, delimiter="\t")
            header = next(reader, None)
    except OSError as exc:
        raise CharacterManifestError(f"cannot read character table {path}: {exc}") from exc
    if not header:
        raise CharacterManifestError("character table has no header")
    _header_kind(header)
    return tuple(normalized_text(value) for value in header)


def load_character_table(path: Path) -> list[dict[str, str]]:
    """Read either the maintained six-column or supplied four-column table."""

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            fields = tuple(reader.fieldnames or ())
            table_kind, mapped_fields = _header_kind(fields)
            rows: list[dict[str, str]] = []
            seen: set[str] = set()
            seen_tokens: set[str] = set()
            for line, raw in enumerate(reader, start=2):
                if None in raw:
                    raise CharacterManifestError(f"line {line}: too many TSV fields")
                if table_kind == "maintained":
                    row = {
                        field: ensure_no_control(normalized_text(raw.get(field, "")), field, line)
                        for field in TABLE_COLUMNS
                    }
                    row["rarity"] = ""
                    row["pinyin"] = ""
                else:
                    raw_by_canonical = {
                        canonical: raw.get(original, "")
                        for original, canonical in zip(fields, mapped_fields)
                    }
                    rarity = ensure_no_control(
                        normalized_text(raw_by_canonical.get("rarity", "")), "rarity", line
                    ).upper()
                    if rarity not in ALLOWED_RARITIES:
                        raise CharacterManifestError(f"line {line}: unsupported rarity {rarity!r}")
                    japanese = ensure_no_control(
                        normalized_text(raw_by_canonical.get("japanese", "")), "japanese", line
                    )
                    chinese = ensure_no_control(
                        normalized_text(raw_by_canonical.get("chinese", "")), "chinese", line
                    )
                    pinyin = ensure_no_control(
                        normalized_text(raw_by_canonical.get("pinyin", "")), "pinyin", line
                    )
                    token = re.sub(r"[^a-z0-9]+", "", pinyin.lower())
                    row = {
                        "rarity": rarity,
                        "character_id": token,
                        "name_ja": japanese,
                        "name_zh": chinese,
                        # Keep the four-column pinyin visible in both the
                        # explicit pinyin field and the legacy reading slot;
                        # downstream schema/docs must not call it Japanese kana.
                        "reading": pinyin,
                        "pinyin": pinyin,
                        "asset_token": token,
                        "source_ref": f"user-provided-character-table:{path.name}:line-{line}",
                    }
                if not row["character_id"] or not ID_RE.fullmatch(row["character_id"]):
                    raise CharacterManifestError(
                        f"line {line}: character_id must match {ID_RE.pattern!r}"
                    )
                if row["character_id"] in seen:
                    raise CharacterManifestError(f"line {line}: duplicate character_id")
                if not row["name_ja"] or not row["name_zh"]:
                    raise CharacterManifestError(f"line {line}: name_ja/name_zh are required")
                if table_kind == "maintained" and not row["reading"]:
                    raise CharacterManifestError(
                        f"line {line}: reading is required in the six-column form"
                    )
                if not row["asset_token"] or not TOKEN_RE.fullmatch(row["asset_token"].lower()):
                    raise CharacterManifestError(
                        f"line {line}: asset_token must be a lowercase ASCII path token"
                    )
                if not row["source_ref"]:
                    raise CharacterManifestError(f"line {line}: source_ref is required")
                row["asset_token"] = row["asset_token"].lower()
                if row["asset_token"] in seen_tokens:
                    raise CharacterManifestError(f"line {line}: duplicate asset_token")
                seen.add(row["character_id"])
                seen_tokens.add(row["asset_token"])
                rows.append(row)
    except OSError as exc:
        raise CharacterManifestError(f"cannot read character table {path}: {exc}") from exc
    if not rows:
        raise CharacterManifestError("character table has no data rows")
    return rows


def _valid_sha(value: Any) -> str | None:
    text = normalized_text(value).lower()
    return text if SHA256_RE.fullmatch(text) else None


def _texture_record(
    material: dict[str, Any],
    texture_by_output_sha: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    texture_sha = _valid_sha(material.get("texture_output_sha256"))
    matches = texture_by_output_sha.get(texture_sha or "", [])
    if texture_sha is None:
        texture_status = "missing_output_sha256"
    elif len(matches) != 1:
        texture_status = (
            "ambiguous_texture_catalog" if len(matches) > 1 else "missing_texture_catalog"
        )
    else:
        texture_status = "resolved"
    texture = matches[0] if len(matches) == 1 else {}
    return {
        "ordinal": material.get("ordinal"),
        "name": normalized_text(material.get("name")),
        "tex0": normalized_text(material.get("tex0")),
        "technique": normalized_text(material.get("technique")),
        "texture_source_sha256": _valid_sha(material.get("texture_source_sha256")),
        "texture_output_sha256": texture_sha,
        "texture_output": texture.get("output"),
        "texture_status": texture_status,
        "texture_catalog_candidates": [item.get("output") for item in matches],
    }


def _material_signature(materials: Iterable[dict[str, Any]]) -> tuple[Any, ...]:
    return tuple(
        (
            normalized_text(material.get("tex0")).lower(),
            normalized_text(material.get("technique")).lower(),
            _valid_sha(material.get("texture_output_sha256")),
        )
        for material in materials
    )


def load_catalogs(paths: Iterable[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load catalog model rows and resolve their already-published textures."""

    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    catalog_info: list[dict[str, Any]] = []
    for catalog_path in paths:
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CharacterManifestError(f"cannot read catalog {catalog_path}: {exc}") from exc
        if not isinstance(catalog, dict) or not isinstance(catalog.get("models"), list):
            raise CharacterManifestError(f"catalog has no models list: {catalog_path}")
        textures_by_sha: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for texture in catalog.get("textures", []):
            if not isinstance(texture, dict):
                continue
            digest = _valid_sha(texture.get("output_sha256"))
            if digest:
                textures_by_sha[digest].append(
                    {
                        "output": texture.get("output"),
                        "source": texture.get("source"),
                        "source_sha256": _valid_sha(texture.get("source_sha256")),
                        "output_sha256": digest,
                    }
                )
        catalog_info.append(
            {
                "path": str(catalog_path.resolve()),
                "sha256": sha256_file(catalog_path),
                "status": normalized_text(catalog.get("status")),
                "stage": normalized_text(catalog.get("stage")),
                "model_count": len(catalog["models"]),
                "texture_count": len(catalog.get("textures", [])),
            }
        )
        for model_index, model in enumerate(catalog["models"]):
            if not isinstance(model, dict):
                continue
            mesh_sha = _valid_sha(model.get("mesh_sha256"))
            if mesh_sha is None:
                continue
            logical_paths = sorted(
                {
                    normalized_logical_path(value)
                    for value in model.get("mesh_logical_paths", [])
                    if normalized_text(value)
                },
                key=str.lower,
            )
            if not logical_paths:
                continue
            raw_materials = [item for item in model.get("materials", []) if isinstance(item, dict)]
            materials = [_texture_record(item, textures_by_sha) for item in raw_materials]
            material_signature = _material_signature(materials)
            output_path = normalized_text(model.get("output"))
            output_sha = _valid_sha(model.get("output_sha256"))
            output_verified = False
            if output_path:
                candidate_output = Path(output_path)
                if candidate_output.is_file() and not candidate_output.is_symlink() and output_sha:
                    try:
                        output_verified = sha256_file(candidate_output) == output_sha
                    except OSError:
                        output_verified = False
            join_status = "joined"
            if normalized_text(model.get("status")) != "converted":
                join_status = "model_unresolved"
            elif not materials:
                join_status = "material_unresolved"
            elif any(item["texture_status"] != "resolved" for item in materials):
                join_status = "texture_unresolved"
            for logical_path in logical_paths:
                key = (logical_path, mesh_sha)
                row = {
                    "logical_path": logical_path,
                    "mesh_sha256": mesh_sha,
                    "model_status": normalized_text(model.get("status")),
                    "join_status": join_status,
                    "output": output_path or None,
                    "output_sha256": output_sha,
                    "output_bytes": model.get("output_bytes"),
                    "output_verified": output_verified,
                    "material_source": model.get("material_source"),
                    "material_sha256": _valid_sha(model.get("material_sha256")),
                    "material_resolution": model.get("material_resolution"),
                    "materials": materials,
                    "association_evidence": normalized_text(model.get("association_evidence")),
                    "catalog_manifests": [str(catalog_path.resolve())],
                    "catalog_model_indices": [model_index],
                    "catalog_signatures": [material_signature],
                }
                existing = candidates.get(key)
                if existing is None:
                    candidates[key] = row
                else:
                    existing["catalog_manifests"].append(str(catalog_path.resolve()))
                    existing["catalog_model_indices"].append(model_index)
                    if material_signature not in existing["catalog_signatures"]:
                        existing["catalog_signatures"].append(material_signature)
                        existing["join_status"] = "catalog_conflict"
    rows = sorted(candidates.values(), key=lambda row: (row["logical_path"], row["mesh_sha256"]))
    for row in rows:
        row["catalog_conflict"] = len(row.pop("catalog_signatures")) > 1
    return rows, catalog_info


def _normalize_reference(raw: Any, index: int, evidence_path: Path) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CharacterManifestError(f"evidence reference {index} is not an object")
    reference_id = normalized_text(raw.get("reference_id")).lower()
    kind = normalized_text(raw.get("kind")).lower() or "image"
    label = normalized_text(raw.get("label"))
    if not REFERENCE_ID_RE.fullmatch(reference_id):
        raise CharacterManifestError(
            f"evidence reference {index} has invalid reference_id {reference_id!r}"
        )
    if kind not in ALLOWED_REFERENCE_KINDS:
        raise CharacterManifestError(
            f"evidence reference {reference_id} has unsupported kind {kind!r}"
        )

    declared_sha = _valid_sha(raw.get("sha256"))
    path_text = normalized_text(raw.get("path"))
    resolved_path: Path | None = None
    file_verified = False
    if path_text:
        candidate = Path(path_text).expanduser()
        if not candidate.is_absolute():
            candidate = evidence_path.parent / candidate
        resolved_path = candidate.resolve(strict=False)
        if not resolved_path.is_file() or resolved_path.is_symlink():
            raise CharacterManifestError(
                f"evidence reference {reference_id} path is missing or unsafe: {resolved_path}"
            )
        actual_sha = sha256_file(resolved_path)
        if declared_sha is not None and actual_sha != declared_sha:
            raise CharacterManifestError(
                f"evidence reference {reference_id} SHA-256 does not match the file"
            )
        declared_sha = actual_sha
        file_verified = True

    source_ref = normalized_text(raw.get("source_ref"))
    url = normalized_text(raw.get("url"))
    if resolved_path is None and not source_ref and not url:
        raise CharacterManifestError(
            f"evidence reference {reference_id} needs path, source_ref, or url"
        )
    if kind == "image" and declared_sha is None:
        raise CharacterManifestError(f"image evidence reference {reference_id} requires a SHA-256")
    return {
        "reference_id": reference_id,
        "kind": kind,
        "label": label or reference_id,
        "sha256": declared_sha,
        "path": str(resolved_path) if resolved_path is not None else None,
        "source_ref": source_ref or None,
        "url": url or None,
        "note": normalized_text(raw.get("note")) or None,
        "file_verified": file_verified,
    }


def load_evidence(path: Path | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if path is None:
        return None, None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CharacterManifestError(f"cannot read evidence map {path}: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("variants"), list):
        raise CharacterManifestError("evidence map must contain a variants list")
    references: list[dict[str, Any]] = []
    references_by_id: dict[str, dict[str, Any]] = {}
    raw_references = document.get("references", [])
    if not isinstance(raw_references, list):
        raise CharacterManifestError("evidence references must be a list")
    for index, raw_reference in enumerate(raw_references):
        reference = _normalize_reference(raw_reference, index, path)
        reference_id = reference["reference_id"]
        if reference_id in references_by_id:
            raise CharacterManifestError(f"duplicate evidence reference_id: {reference_id}")
        references.append(reference)
        references_by_id[reference_id] = reference

    normalized: dict[str, Any] = {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "schema_version": document.get("schema_version"),
        "character_id": normalized_text(document.get("character_id")),
        "references": references,
        "variants": [],
        "unresolved": document.get("unresolved", []),
    }
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(document["variants"]):
        if not isinstance(raw, dict):
            raise CharacterManifestError(f"evidence variant {index} is not an object")
        character_id = normalized_text(raw.get("character_id")) or normalized["character_id"]
        variant_id = normalized_text(raw.get("variant_id"))
        logical_path = normalized_logical_path(raw.get("logical_path"))
        status = normalized_text(raw.get("status"))
        confidence = normalized_text(raw.get("confidence"))
        raw_reference_ids = raw.get("reference_ids", [])
        if not isinstance(raw_reference_ids, list):
            raise CharacterManifestError(f"evidence variant {index} reference_ids must be a list")
        reference_ids = [normalized_text(value).lower() for value in raw_reference_ids]
        if any(not REFERENCE_ID_RE.fullmatch(value) for value in reference_ids):
            raise CharacterManifestError(
                f"evidence variant {index} contains an invalid reference_id"
            )
        if len(reference_ids) != len(set(reference_ids)):
            raise CharacterManifestError(
                f"evidence variant {index} contains duplicate reference_ids"
            )
        missing_reference_ids = [value for value in reference_ids if value not in references_by_id]
        if missing_reference_ids:
            raise CharacterManifestError(
                f"evidence variant {index} references unknown evidence: {missing_reference_ids}"
            )
        if not character_id or not variant_id or not logical_path:
            raise CharacterManifestError(
                f"evidence variant {index} lacks character_id/variant_id/logical_path"
            )
        if status not in ALLOWED_VARIANT_STATUS:
            raise CharacterManifestError(
                f"evidence variant {index} has unsupported status {status!r}"
            )
        if status == "verified" and confidence != "high":
            raise CharacterManifestError(
                f"verified evidence variant {index} must have high confidence"
            )
        image_references = [
            references_by_id[value]
            for value in reference_ids
            if references_by_id[value]["kind"] == "image"
        ]
        if status == "verified" and not image_references:
            raise CharacterManifestError(
                f"verified evidence variant {index} requires a SHA-256-pinned image reference"
            )
        if status == "verified" and (
            not normalized_text(raw.get("evidence_ref"))
            or not normalized_text(raw.get("evidence_note"))
        ):
            raise CharacterManifestError(
                f"verified evidence variant {index} requires evidence_ref and evidence_note"
            )
        key = (character_id, logical_path)
        if key in seen:
            raise CharacterManifestError(
                f"duplicate evidence path for {character_id}: {logical_path}"
            )
        seen.add(key)
        normalized["variants"].append(
            {
                "character_id": character_id,
                "variant_id": variant_id,
                "logical_path": logical_path,
                "status": status,
                "confidence": confidence or "unknown",
                "reference_ids": reference_ids,
                "visual_reference_sha256s": [
                    item["sha256"] for item in image_references if item["sha256"] is not None
                ],
                "label_ja": normalized_text(raw.get("label_ja")),
                "evidence_ref": normalized_text(raw.get("evidence_ref")),
                "evidence_note": normalized_text(raw.get("evidence_note")),
            }
        )
    return normalized, document


def token_matches(logical_path: str, token: str) -> bool:
    """Match a family token at a path-segment boundary, never a substring."""

    token_pattern = re.escape(token.lower())
    for segment in normalized_logical_path(logical_path).split("/"):
        segment = segment.rsplit(".", 1)[0]
        if segment == token.lower() or re.search(
            rf"(?:^|[^a-z0-9]){token_pattern}(?:$|[^a-z0-9])", segment
        ):
            return True
    return False


def _evidence_lookup(document: dict[str, Any] | None) -> dict[tuple[str, str], dict[str, Any]]:
    if not document:
        return {}
    return {
        (item["character_id"], item["logical_path"]): item for item in document.get("variants", [])
    }


def _safe_count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _candidate_publication_status(model: dict[str, Any], selection_status: str) -> str:
    if model["join_status"] != "joined":
        return "blocked-technical-join"
    if not model["output_verified"]:
        return "blocked-output-verification"
    if selection_status != "verified":
        return "blocked-visual-evidence"
    return "verified"


def _build_candidate(
    character: dict[str, Any],
    model: dict[str, Any],
    evidence_by_path: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    """Create one model candidate and apply publication gates."""

    evidence = evidence_by_path.get((character["character_id"], model["logical_path"]))
    selection_status = evidence["status"] if evidence else "unmapped-candidate"
    confidence = evidence["confidence"] if evidence else "unknown"
    return {
        "variant_id": evidence.get("variant_id") if evidence else None,
        "selection_status": selection_status,
        "publication_status": _candidate_publication_status(model, selection_status),
        "confidence": confidence,
        "visual_reference_ids": evidence.get("reference_ids", []) if evidence else [],
        "visual_reference_sha256s": evidence.get("visual_reference_sha256s", [])
        if evidence
        else [],
        "label_ja": evidence.get("label_ja") if evidence else None,
        "evidence_ref": evidence.get("evidence_ref") if evidence else None,
        "evidence_note": evidence.get("evidence_note") if evidence else None,
        "logical_path": model["logical_path"],
        "mesh_sha256": model["mesh_sha256"],
        "model_status": model["model_status"],
        "join_status": model["join_status"],
        "output": model["output"],
        "output_sha256": model["output_sha256"],
        "output_bytes": model["output_bytes"],
        "output_verified": model["output_verified"],
        "material_source": model["material_source"],
        "material_sha256": model["material_sha256"],
        "material_resolution": model["material_resolution"],
        "materials": model["materials"],
        "association_evidence": model["association_evidence"],
        "catalog_conflict": model["catalog_conflict"],
        "catalog_manifests": model["catalog_manifests"],
    }


def _normalized_candidate_row(
    character: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    """Convert one candidate to the stable, tabular publication shape."""

    return {
        "rarity": character.get("rarity", ""),
        "character_id": character["character_id"],
        "name_ja": character["name_ja"],
        "name_zh": character["name_zh"],
        "reading": character["reading"],
        "pinyin": character.get("pinyin", ""),
        "asset_token": character["asset_token"],
        "variant_id": candidate["variant_id"] or "",
        "selection_status": candidate["selection_status"],
        "publication_status": candidate["publication_status"],
        "confidence": candidate["confidence"],
        "logical_path": candidate["logical_path"],
        "mesh_sha256": candidate["mesh_sha256"],
        "model_status": candidate["model_status"],
        "join_status": candidate["join_status"],
        "model_output_sha256": candidate["output_sha256"] or "",
        "model_output_verified": str(candidate["output_verified"]).lower(),
        "material_count": len(candidate["materials"]),
        "texture_output_sha256s": ";".join(
            item["texture_output_sha256"] or "" for item in candidate["materials"]
        ),
        "visual_reference_ids": ";".join(candidate["visual_reference_ids"]),
        "visual_reference_sha256s": ";".join(candidate["visual_reference_sha256s"]),
        "evidence_ref": candidate["evidence_ref"] or "",
    }


def _candidate_unresolved(
    character: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any] | None:
    if candidate["publication_status"] == "verified":
        return None
    if candidate["join_status"] != "joined":
        reason = "catalog_join_not_complete"
    elif not candidate["output_verified"]:
        reason = "model_output_hash_not_verified"
    else:
        reason = "visual_reference_not_verified"
    return {
        "character_id": character["character_id"],
        "logical_path": candidate["logical_path"],
        "reason": reason,
    }


def _evidence_unresolved_for_character(
    character: dict[str, Any],
    evidence_document: dict[str, Any] | None,
    evidence_meta: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return evidence-only unresolved rows for one character."""

    if not evidence_document:
        return [], []
    evidence_unresolved: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    fallback_character_id = evidence_meta.get("character_id") if evidence_meta else None
    for item in evidence_document.get("unresolved", []):
        if not isinstance(item, dict):
            continue
        evidence_character = normalized_text(item.get("character_id")) or fallback_character_id
        if evidence_character != character["character_id"]:
            continue
        label_ja = normalized_text(item.get("label_ja"))
        reason = normalized_text(item.get("reason"))
        evidence_ref = normalized_text(item.get("evidence_ref"))
        evidence_unresolved.append(
            {"label_ja": label_ja, "reason": reason, "evidence_ref": evidence_ref}
        )
        unresolved.append(
            {
                "character_id": character["character_id"],
                "logical_path": None,
                "reason": "evidence_unresolved",
                "detail": reason,
            }
        )
    return evidence_unresolved, unresolved


def _no_candidate_row(character: dict[str, Any]) -> dict[str, Any]:
    return {
        "rarity": character.get("rarity", ""),
        "character_id": character["character_id"],
        "name_ja": character["name_ja"],
        "name_zh": character["name_zh"],
        "reading": character["reading"],
        "pinyin": character.get("pinyin", ""),
        "asset_token": character["asset_token"],
        "variant_id": "",
        "selection_status": "unresolved",
        "publication_status": "blocked-no-candidate",
        "confidence": "unknown",
        "logical_path": "",
        "mesh_sha256": "",
        "model_status": "",
        "join_status": "no_logical_path_candidate",
        "model_output_sha256": "",
        "model_output_verified": "false",
        "material_count": 0,
        "texture_output_sha256s": "",
        "visual_reference_ids": "",
        "visual_reference_sha256s": "",
        "evidence_ref": "",
    }


def _join_character(
    character: dict[str, Any],
    model_rows: list[dict[str, Any]],
    evidence_by_path: dict[tuple[str, str], dict[str, Any]],
    evidence_document: dict[str, Any] | None,
    evidence_meta: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Join one character to every matching model while retaining ambiguity."""

    candidates: list[dict[str, Any]] = []
    normalized_rows: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for model in model_rows:
        if not token_matches(model["logical_path"], character["asset_token"]):
            continue
        candidate = _build_candidate(character, model, evidence_by_path)
        candidates.append(candidate)
        normalized_rows.append(_normalized_candidate_row(character, candidate))
        unresolved_item = _candidate_unresolved(character, candidate)
        if unresolved_item is not None:
            unresolved.append(unresolved_item)

    evidence_unresolved, evidence_failures = _evidence_unresolved_for_character(
        character, evidence_document, evidence_meta
    )
    unresolved.extend(evidence_failures)
    if not candidates:
        unresolved.append(
            {
                "character_id": character["character_id"],
                "logical_path": None,
                "reason": "no_logical_path_candidate",
            }
        )
        normalized_rows.append(_no_candidate_row(character))

    joined = {
        **character,
        "model_candidates": sorted(
            candidates, key=lambda item: (item["logical_path"], item["mesh_sha256"])
        ),
        "evidence_unresolved": evidence_unresolved,
        "candidate_count": len(candidates),
        "verified_count": sum(item["publication_status"] == "verified" for item in candidates),
        "selection_policy": (
            "publication requires a technically verified model+texture join and explicit "
            "SHA-256-pinned image evidence for the exact logical path"
        ),
    }
    return joined, normalized_rows, unresolved


def _load_join_inputs(
    table_path: Path,
    catalog_paths: Iterable[Path],
    output_dir: Path,
    evidence_path: Path | None,
) -> tuple[
    Path,
    Path,
    list[dict[str, str]],
    tuple[str, ...],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any] | None,
    dict[str, Any] | None,
    dict[tuple[str, str], dict[str, Any]],
]:
    """Validate publication inputs and load independent source indexes."""

    table_path = table_path.resolve()
    catalog_paths = [path.resolve() for path in catalog_paths]
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise CharacterManifestError(
            f"refusing to overwrite existing output directory: {output_dir}"
        )
    if not table_path.is_file() or table_path.is_symlink():
        raise CharacterManifestError(f"character table is missing or unsafe: {table_path}")

    rows = load_character_table(table_path)
    input_columns = character_table_columns(table_path)
    model_rows, catalog_info = load_catalogs(catalog_paths)
    evidence_meta, evidence_document = load_evidence(
        evidence_path.resolve() if evidence_path else None
    )
    evidence_by_path = _evidence_lookup(evidence_meta)
    return (
        table_path,
        output_dir,
        rows,
        input_columns,
        model_rows,
        catalog_info,
        evidence_meta,
        evidence_document,
        evidence_by_path,
    )


def _join_characters(
    rows: list[dict[str, str]],
    model_rows: list[dict[str, Any]],
    evidence_by_path: dict[tuple[str, str], dict[str, Any]],
    evidence_document: dict[str, Any] | None,
    evidence_meta: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Join every catalog character and retain normalized/unresolved rows."""

    characters: list[dict[str, Any]] = []
    normalized_rows: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for character in rows:
        joined, rows_for_character, failures_for_character = _join_character(
            character,
            model_rows,
            evidence_by_path,
            evidence_document,
            evidence_meta,
        )
        characters.append(joined)
        normalized_rows.extend(rows_for_character)
        unresolved.extend(failures_for_character)
    return characters, normalized_rows, unresolved


def _join_counts(
    characters: list[dict[str, Any]], unresolved: list[dict[str, Any]]
) -> dict[str, int]:
    """Summarize join outcomes without mutating character records."""

    return {
        "characters": len(characters),
        "candidate_models": sum(item["candidate_count"] for item in characters),
        "joined_models": sum(
            item["join_status"] == "joined"
            for character in characters
            for item in character["model_candidates"]
        ),
        "verified_variants": sum(item["verified_count"] for item in characters),
        "auxiliary_candidates": sum(
            item["selection_status"] == "auxiliary"
            for character in characters
            for item in character["model_candidates"]
        ),
        "unresolved_records": len(unresolved),
    }


def _build_join_manifest(
    *,
    table_path: Path,
    output_dir: Path,
    input_columns: tuple[str, ...],
    rows: list[dict[str, str]],
    catalog_info: list[dict[str, Any]],
    evidence_meta: dict[str, Any] | None,
    characters: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the character publication document without writing files."""

    return {
        "schema_version": 1,
        "stage": "character-asset-join",
        "created_at": utc_now(),
        "status": "complete",
        "source_policy": "read-only catalog join; character table and evidence are metadata; raw payloads are untouched",
        "policy": {
            "name_to_asset": "explicit lowercase ASCII asset_token matched at logical path segment boundaries",
            "variant_selection": "exact character_id + logical_path evidence only; all other family candidates remain unresolved",
            "visual_publication_gate": "verified output requires high-confidence SHA-256-pinned image evidence",
            "material_texture_join": "reuse catalog material Tex0/output hashes; no MTL or texture inference in this stage",
            "duplicate_materials": "retain catalog material_resolution and catalog conflicts; never choose here",
            "output_verification": "converted model output SHA-256 is checked when the declared output exists",
        },
        "implementation": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__).resolve()),
            "reproduction_argv": [sys.executable, *sys.argv],
        },
        "input_table": {
            "path": str(table_path),
            "sha256": sha256_file(table_path),
            "columns": list(input_columns),
            "normalized_columns": list(TSV_COLUMNS),
            "row_count": len(rows),
        },
        "catalogs": catalog_info,
        "evidence_map": evidence_meta,
        "counts": _join_counts(characters, unresolved),
        "normalized_tsv": str(output_dir / "normalized-character-assets.tsv"),
        "characters": characters,
        "unresolved": unresolved,
    }


def _assemble_manifest(
    table_path: Path,
    catalog_paths: Iterable[Path],
    output_dir: Path,
    evidence_path: Path | None = None,
) -> dict[str, Any]:
    """Assemble join results without creating or writing the publication tree."""

    (
        table_path,
        output_dir,
        rows,
        input_columns,
        model_rows,
        catalog_info,
        evidence_meta,
        evidence_document,
        evidence_by_path,
    ) = _load_join_inputs(table_path, catalog_paths, output_dir, evidence_path)
    characters, normalized_rows, unresolved = _join_characters(
        rows,
        model_rows,
        evidence_by_path,
        evidence_document,
        evidence_meta,
    )
    manifest = _build_join_manifest(
        table_path=table_path,
        output_dir=output_dir,
        input_columns=input_columns,
        rows=rows,
        catalog_info=catalog_info,
        evidence_meta=evidence_meta,
        characters=characters,
        unresolved=unresolved,
    )
    return {"manifest": manifest, "normalized_rows": normalized_rows}


def build_manifest(
    table_path: Path,
    catalog_paths: Iterable[Path],
    output_dir: Path,
    evidence_path: Path | None = None,
) -> dict[str, Any]:
    """Assemble a manifest, then publish its TSV and JSON atomically."""

    assembled = _assemble_manifest(table_path, catalog_paths, output_dir, evidence_path)
    manifest = assembled["manifest"]
    normalized_rows = assembled["normalized_rows"]
    output_path = Path(manifest["normalized_tsv"]).parent
    output_path.mkdir(parents=False)
    write_tsv_new(output_path / "normalized-character-assets.tsv", normalized_rows)
    write_json_new(output_path / "character-asset-manifest.json", manifest)
    return manifest


def _new_file(path: Path, payload: bytes) -> None:
    try:
        write_bytes_atomic(path, payload, overwrite=False)
    except FileExistsError as exc:
        raise CharacterManifestError(f"refusing to overwrite output file: {path}") from exc


def write_json_new(path: Path, value: dict[str, Any]) -> None:
    _new_file(path, json_bytes(value))


def write_tsv_new(path: Path, rows: list[dict[str, Any]]) -> None:
    from io import StringIO

    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=TSV_COLUMNS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    _new_file(path, buffer.getvalue().encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--characters",
        required=True,
        type=Path,
        help="UTF-8 TSV: maintained six columns or rarity/japanese/chinese/pinyin four-column form",
    )
    parser.add_argument(
        "--catalog",
        action="append",
        required=True,
        type=Path,
        help="textured-static-manifest.json (repeatable)",
    )
    parser.add_argument(
        "--evidence", type=Path, help="optional exact logical-path variant evidence JSON"
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="new, non-existing output run directory"
    )
    args = parser.parse_args(argv)
    try:
        manifest = build_manifest(args.characters, args.catalog, args.output, args.evidence)
    except (CharacterManifestError, OSError, ValueError) as exc:
        print(f"character asset join failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "output": str(Path(args.output).resolve()),
                "counts": manifest["counts"],
                "status": manifest["status"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
