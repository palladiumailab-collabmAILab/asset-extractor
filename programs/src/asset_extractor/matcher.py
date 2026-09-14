from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

from .common import atomic_write_json, config_hash, sha256_file, tool_metadata, utc_now
from .errors import ExtractionError


SEPARATOR_RE = re.compile(r"[^a-z0-9]+")
VARIANT_PREFIX_RE = re.compile(r"^(?:s|c|v|skin|costume|variant)\d+$")
VARIANT_SUFFIXES = {"show", "display", "preview", "icon", "portrait", "head", "body"}
MODEL_TYPES = {"mesh", "model", "gltf", "glb", "fbx", "obj"}
IMAGE_TYPES = {"texture", "sprite", "illustration", "image", "png", "jpg", "jpeg", "tga", "ktx", "dds", "pvr"}


def normalize_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return SEPARATOR_RE.sub("", normalized)


def path_tokens(logical_path: str) -> list[tuple[str, str]]:
    """Return exact and variant-normalized tokens from a logical asset path."""
    path = PurePosixPath(logical_path.replace("\\", "/"))
    result: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(method: str, value: str) -> None:
        token = unicodedata.normalize("NFKC", value).casefold() if method == "exact" else normalize_token(value)
        pair = (method, token)
        if token and pair not in seen:
            result.append(pair)
            seen.add(pair)

    for part in path.parts:
        stem = PurePosixPath(part).stem
        add("exact", part)
        add("exact", stem)
        add("normalized", part)
        add("normalized", stem)
        components = [item for item in re.split(r"[_\-.]+", stem.casefold()) if item]
        for component in components:
            add("normalized", component)
        if components and (VARIANT_PREFIX_RE.fullmatch(components[0]) or components[0] == "j"):
            add("normalized", "_".join(components[1:]))
        if components and components[-1] in VARIANT_SUFFIXES:
            add("normalized", "_".join(components[:-1]))
    return result


def _aliases(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in re.split(r"[;,|]", str(value)) if item.strip()]


def _entity(raw: dict[str, Any], line: int) -> dict[str, Any]:
    entity_id = str(raw.get("entity_id") or raw.get("character_id") or raw.get("asset_token") or raw.get("romanized") or "").strip()
    canonical = str(raw.get("asset_token") or raw.get("romanized") or raw.get("pinyin") or entity_id).strip()
    if not entity_id or not canonical:
        raise ExtractionError(f"dictionary row {line} lacks entity_id and canonical token")
    aliases = _aliases(raw.get("aliases"))
    return {
        "entity_id": entity_id,
        "entity_type": str(raw.get("entity_type") or "character").strip(),
        "canonical_token": canonical,
        "aliases": aliases,
        "name_ja": str(raw.get("name_ja") or raw.get("japanese") or "").strip(),
        "name_zh": str(raw.get("name_zh") or raw.get("chinese") or "").strip(),
        "reading": str(raw.get("reading") or "").strip(),
        "romanized": str(raw.get("romanized") or raw.get("pinyin") or canonical).strip(),
        "rarity": str(raw.get("rarity") or "").strip(),
        "metadata": {key: value for key, value in raw.items() if key not in {
            "entity_id", "character_id", "entity_type", "asset_token", "aliases",
            "name_ja", "japanese", "name_zh", "chinese", "reading", "romanized", "pinyin", "rarity",
        }},
    }


def load_dictionary(path: Path) -> list[dict[str, Any]]:
    try:
        if path.suffix.casefold() == ".json":
            document = json.loads(path.read_text(encoding="utf-8-sig"))
            rows = document.get("entities") if isinstance(document, dict) else document
            if not isinstance(rows, list):
                raise ExtractionError("JSON dictionary must be an array or contain entities[]")
            entities = [_entity(row, index) for index, row in enumerate(rows, 1) if isinstance(row, dict)]
        else:
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                entities = [_entity(dict(row), index) for index, row in enumerate(csv.DictReader(stream), 2)]
    except (OSError, json.JSONDecodeError, csv.Error) as exc:
        raise ExtractionError(f"cannot read dictionary {path}: {exc}") from exc
    if not entities:
        raise ExtractionError("dictionary contains no entities")
    ids: set[str] = set()
    keys: dict[str, str] = {}
    for entity in entities:
        if entity["entity_id"] in ids:
            raise ExtractionError(f"duplicate entity_id: {entity['entity_id']}")
        ids.add(entity["entity_id"])
        for value in [entity["canonical_token"], *entity["aliases"]]:
            key = normalize_token(value)
            if key in keys and keys[key] != entity["entity_id"]:
                raise ExtractionError(f"ambiguous dictionary token {value!r}")
            keys[key] = entity["entity_id"]
    return entities


def load_assets(path: Path) -> list[dict[str, Any]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExtractionError(f"cannot read asset manifest {path}: {exc}") from exc
    if isinstance(document, list):
        rows = document
    elif isinstance(document, dict):
        rows = document.get("assets", document.get("entries"))
    else:
        rows = None
    if not isinstance(rows, list):
        raise ExtractionError("asset manifest must be an array or contain assets[]/entries[]")
    assets: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ExtractionError(f"asset row {index} must be an object")
        logical_path = row.get("logical_path") or row.get("source_path") or row.get("path")
        if not isinstance(logical_path, str) or not logical_path.strip():
            assets.append({**row, "_input_index": index, "_logical_path": None, "_asset_type": str(row.get("asset_type") or row.get("kind") or "unknown")})
            continue
        assets.append({**row, "_input_index": index, "_logical_path": logical_path.replace("\\", "/"), "_asset_type": str(row.get("asset_type") or row.get("kind") or PurePosixPath(logical_path).suffix.lstrip(".") or "unknown")})
    return assets


def _match_one(asset: dict[str, Any], entities: list[dict[str, Any]]) -> dict[str, Any]:
    logical_path = asset["_logical_path"]
    if logical_path is None:
        return {"entity": None, "matched_key": None, "match_method": "unmatched", "match_confidence": "unmatched", "evidence": "logical_path_missing"}
    tokens = path_tokens(logical_path)
    candidates: list[tuple[int, str, dict[str, Any], str]] = []
    for entity in entities:
        canonical_exact = unicodedata.normalize("NFKC", entity["canonical_token"]).casefold()
        canonical_normalized = normalize_token(entity["canonical_token"])
        aliases = {normalize_token(value): value for value in entity["aliases"]}
        for token_method, token in tokens:
            if token_method == "exact" and token == canonical_exact:
                candidates.append((0, "exact", entity, entity["canonical_token"]))
            elif token == canonical_normalized:
                candidates.append((1, "normalized", entity, entity["canonical_token"]))
            elif token in aliases:
                candidates.append((2, "alias", entity, aliases[token]))
    if not candidates:
        return {"entity": None, "matched_key": None, "match_method": "unmatched", "match_confidence": "unmatched", "evidence": "no_dictionary_token_match"}
    best_priority = min(item[0] for item in candidates)
    best = {item[2]["entity_id"]: item for item in candidates if item[0] == best_priority}
    if len(best) != 1:
        return {"entity": None, "matched_key": None, "match_method": "heuristic", "match_confidence": "ambiguous", "evidence": "multiple_entities_share_path_tokens"}
    _, method, entity, key = next(iter(best.values()))
    return {"entity": entity, "matched_key": key, "match_method": method, "match_confidence": method, "evidence": "logical_path_name"}


def asset_family(asset_type: str) -> str:
    value = normalize_token(asset_type)
    if value in MODEL_TYPES:
        return "3d"
    if value in IMAGE_TYPES:
        return "image"
    return "other"


def build_match_manifest(dictionary_path: Path, asset_path: Path) -> dict[str, Any]:
    dictionary_path = dictionary_path.resolve()
    asset_path = asset_path.resolve()
    entities = load_dictionary(dictionary_path)
    assets = load_assets(asset_path)
    matches: list[dict[str, Any]] = []
    groups: dict[str, list[int]] = defaultdict(list)
    for asset in assets:
        decision = _match_one(asset, entities)
        entity = decision["entity"]
        row = {
            "input_index": asset["_input_index"],
            "asset_id": asset.get("asset_id"),
            "source_asset": {key: value for key, value in asset.items() if not key.startswith("_")},
            "logical_path": asset["_logical_path"],
            "asset_type": asset["_asset_type"],
            "asset_family": asset_family(asset["_asset_type"]),
            **decision,
            "same_name_pair_status": "unmatched",
            "same_name_peer_indices": [],
        }
        if entity:
            groups[entity["entity_id"]].append(len(matches))
        matches.append(row)
    for indices in groups.values():
        families = {matches[index]["asset_family"] for index in indices}
        paired = "3d" in families and "image" in families
        for index in indices:
            is_pair_member = matches[index]["asset_family"] in {"3d", "image"}
            matches[index]["same_name_pair_status"] = (
                "paired-3d-image" if paired and is_pair_member else "matched-single-family"
            )
            matches[index]["same_name_peer_indices"] = [item for item in indices if item != index]
    return {
        "schema_version": 1,
        "operation": "match-assets-by-logical-name",
        "created_at": utc_now(),
        "tool": tool_metadata(),
        "inputs": {
            "dictionary": str(dictionary_path),
            "dictionary_sha256": sha256_file(dictionary_path),
            "assets": str(asset_path),
            "assets_sha256": sha256_file(asset_path),
        },
        "policy": {
            "primary_rule": "assets sharing a dictionary-backed logical name belong to the same entity candidate set",
            "pair_rule": "only the matched 3D and image members are marked paired-3d-image; other asset families remain separate",
            "automatic_methods": ["exact", "normalized", "alias"],
            "heuristic_is_not_automatic": True,
        },
        "configuration_sha256": config_hash({"normalizer": "nfkc-casefold-separator-v1", "variant_prefixes": "s/c/v/skin/costume/variant-number,j", "variant_suffixes": sorted(VARIANT_SUFFIXES)}),
        "summary": {
            "assets": len(matches),
            "matched": sum(item["entity"] is not None for item in matches),
            "unmatched": sum(item["entity"] is None for item in matches),
            "paired_3d_image": sum(item["same_name_pair_status"] == "paired-3d-image" for item in matches),
        },
        "matches": matches,
    }


def write_match_manifest(dictionary_path: Path, asset_path: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise ExtractionError(f"output already exists: {output}")
    manifest = build_match_manifest(dictionary_path, asset_path)
    atomic_write_json(output.resolve(), manifest)
    return manifest
