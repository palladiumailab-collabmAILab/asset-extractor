#!/usr/bin/env python3
"""Run the three-way Onmyoji NPK pilot with provenance and safety evidence.

This adapter deliberately keeps upstream checkouts untouched.  NeoXtractor is
invoked through ``NPKFile.load_entry``/``save_to_file`` (its GUI is not a CLI),
neox_tools through its published ``onmyoji_extractor.unpack`` entry point, and
the maintained parser through ``asset_extractor.pipeline.extract_inputs``.
Only a copied pilot input is passed to neox_tools because that upstream entry
point writes beside its input path.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import shutil
import struct
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


MAX_ENTRY_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024 * 1024
MAX_RATIO = 10_000.0


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def fresh_dir(path: Path) -> None:
    if path.exists():
        raise RuntimeError(f"run destination already exists; refusing overwrite: {path}")
    path.mkdir(parents=True, exist_ok=False)


def canonical_rows(canonical_root: Path, manifest_path: Path) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for item in manifest["copied_files"]:
        path = (canonical_root / item["path"]).resolve()
        if not within(path, canonical_root):
            raise RuntimeError(f"canonical path escapes root: {item['path']}")
        rows.append(
            {
                "path": str(path),
                "manifest_path": item["path"],
                "expected_size": int(item["size"]),
                "expected_sha256": item["sha256"].lower(),
            }
        )
    return rows


def verify_sources(rows: list[dict[str, Any]], phase: str) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for row in rows:
        path = Path(row["path"])
        result = dict(row)
        result["phase"] = phase
        try:
            result["actual_size"] = path.stat().st_size
            result["actual_sha256"] = sha256_file(path)
            result["size_match"] = result["actual_size"] == row["expected_size"]
            result["sha256_match"] = result["actual_sha256"] == row["expected_sha256"]
            result["status"] = "ok" if result["size_match"] and result["sha256_match"] else "mismatch"
        except OSError as exc:
            result.update({"actual_size": None, "actual_sha256": None, "size_match": False, "sha256_match": False, "status": "error", "error": str(exc)})
        results.append(result)
        if result["status"] != "ok":
            failures.append(result)
    return {"schema_version": 1, "phase": phase, "status": "ok" if not failures else "failed", "count": len(results), "failures": failures, "files": results}


def parse_index(source: Path) -> dict[str, Any]:
    size = source.stat().st_size
    with source.open("rb") as handle:
        header = handle.read(24)
        if len(header) != 24 or header[:4] not in {b"NXPK", b"EXPK"}:
            raise RuntimeError(f"unsupported NPK header: {source}")
        count, var1, encrypt_mode, hash_mode, index_offset = struct.unpack("<5I", header[4:24])
        if count == 0:
            info_size = 32
        elif var1 == 1:
            info_size = 32
        else:
            remainder = size - index_offset
            if remainder < 0 or remainder % count:
                raise RuntimeError("index size is not divisible by entry count")
            info_size = remainder // count
        if info_size != 32:
            raise RuntimeError(f"pilot requires 32-byte NPK entries, got {info_size}")
        index_end = index_offset + count * info_size
        if index_offset < 24 or index_end > size:
            raise RuntimeError("index exceeds source bounds")
        handle.seek(index_offset)
        entries: list[dict[str, Any]] = []
        ranges: list[tuple[int, int, int]] = []
        for ordinal in range(count):
            raw = handle.read(info_size)
            if len(raw) != info_size:
                raise RuntimeError(f"truncated index at ordinal {ordinal}")
            payload_id, unknown, offset, packed, unpacked, hash1, hash2, flags = struct.unpack("<8I", raw)
            if offset < 24 or offset > size or packed > size - offset:
                raise RuntimeError(f"entry {ordinal} payload is outside source bounds")
            if packed > MAX_ENTRY_BYTES or unpacked > MAX_ENTRY_BYTES:
                raise RuntimeError(f"entry {ordinal} exceeds safety member limit")
            if unpacked and (not packed or unpacked / packed > MAX_RATIO):
                raise RuntimeError(f"entry {ordinal} exceeds safety expansion ratio")
            ranges.append((offset, offset + packed, ordinal))
            entries.append(
                {
                    "ordinal": ordinal,
                    "payload_id": payload_id,
                    "unknown": unknown,
                    "offset": offset,
                    "packed_bytes": packed,
                    "declared_unpacked_bytes": unpacked,
                    "hash1": hash1,
                    "hash2": hash2,
                    "flags_raw": flags,
                    "compression_flag": flags & 0xFFFF,
                    "encryption_flag": (flags >> 16) & 0xFFFF,
                    "bounds_checked": True,
                }
            )
        for left, right in zip(sorted(ranges), sorted(ranges)[1:]):
            if right[0] < left[1]:
                raise RuntimeError(f"overlapping payload ranges at {left[2]} and {right[2]}")
        total_unpacked = sum(item["declared_unpacked_bytes"] for item in entries)
        if total_unpacked > MAX_TOTAL_BYTES:
            raise RuntimeError(f"declared output exceeds safety total limit: {total_unpacked}")
    return {
        "magic": header[:4].decode("ascii"),
        "entry_count": count,
        "var1": var1,
        "encrypt_mode": encrypt_mode,
        "hash_mode": hash_mode,
        "index_offset": index_offset,
        "index_size": info_size,
        "index_end": index_end,
        "declared_total_unpacked_bytes": total_unpacked,
        "entries": entries,
    }


def magic_type(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            data = handle.read(16)
    except OSError:
        return "unreadable"
    if data.startswith(b"\x89PNG"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"DDS "):
        return "dds"
    if data.startswith(b"PVR\x03") or data.startswith(b"PVR"):
        return "pvr"
    if data.startswith(b"OggS"):
        return "ogg"
    if data.startswith(b"RIFF"):
        return "riff"
    if data.startswith(b"UnityFS"):
        return "unity3d"
    if data.startswith(bytes([0x34, 0x80, 0xC8, 0xBB])):
        return "mesh"
    if data.startswith(b"NXPK"):
        return "nxpk"
    if data.lstrip().startswith(b"<?xml"):
        return "xml"
    if data.lstrip().startswith(b"{"):
        return "json"
    return "unknown"


def output_row(base: dict[str, Any], tool: str, tool_meta: dict[str, Any], status: str, output: Path | None = None, error: str | None = None, name: str | None = None, transforms: list[str] | None = None) -> dict[str, Any]:
    row = {
        "tool": tool,
        "tool_metadata": tool_meta,
        "ordinal": base["ordinal"],
        "payload_id": base["payload_id"],
        "name": name,
        "offset": base["offset"],
        "packed_bytes": base["packed_bytes"],
        "declared_unpacked_bytes": base["declared_unpacked_bytes"],
        "flags_raw": base["flags_raw"],
        "compression_flag": base["compression_flag"],
        "encryption_flag": base["encryption_flag"],
        "status": status,
        "error": error,
        "output_path": str(output) if output else None,
        "actual_size": output.stat().st_size if output and output.exists() else None,
        "output_sha256": sha256_file(output) if output and output.exists() else None,
        "detected_type": magic_type(output) if output and output.exists() else None,
        "transforms": transforms or [],
        "bounds_checked": base.get("bounds_checked", True),
        "size_checked": bool(output and output.exists() and output.stat().st_size == base["declared_unpacked_bytes"]) if status == "ok" else False,
    }
    return row


def tool_version(repo: Path) -> dict[str, Any]:
    import subprocess

    commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"], text=True).strip()
    tracked = subprocess.check_output(["git", "-C", str(repo), "ls-files", "-s"], text=True).encode()
    diff = subprocess.check_output(["git", "-C", str(repo), "diff", "--no-ext-diff", "--binary"])
    return {
        "repository": str(repo),
        "commit": commit,
        "tree": tree,
        "tracked_files_sha256": hashlib.sha256(tracked).hexdigest(),
        "working_tree_clean": not bool(diff),
        "working_tree_diff_sha256": hashlib.sha256(diff).hexdigest(),
    }


def run_neox(source: Path, destination: Path, index: dict[str, Any], repo: Path, config: Path) -> dict[str, Any]:
    fresh_dir(destination)
    tool_meta = tool_version(repo)
    tool_meta["config_path"] = str(config)
    tool_meta["config_sha256"] = sha256_file(config)
    original_sys_path = sys.path.copy()
    sys.path.insert(0, str(repo))
    started = time.time()
    rows: list[dict[str, Any]] = []
    try:
        npk_file = importlib.import_module("core.npk.npk_file")
        class_types = importlib.import_module("core.npk.class_types")
        archive = npk_file.NPKFile(str(source), class_types.NPKReadOptions(decryption_key=150))
        if archive.file_count != index["entry_count"] or archive.info_size != index["index_size"]:
            raise RuntimeError(f"NeoXtractor header/index mismatch: {archive.file_count}/{archive.info_size}")
        with source.open("rb") as handle:
            for base, upstream_index in zip(index["entries"], archive.indices):
                target = destination / f"{base['ordinal']:07d}_{base['payload_id']:08x}.bin"
                if not within(target, destination) or target.exists():
                    raise RuntimeError(f"unsafe or existing NeoXtractor destination: {target}")
                try:
                    archive.load_entry(base["ordinal"], handle)
                    entry = archive.entries[base["ordinal"]]
                    # Use the upstream extraction API; only the destination name
                    # is controlled by this adapter to keep paths safe.
                    ext = entry.extension or "bin"
                    target = destination / f"{base['ordinal']:07d}_{base['payload_id']:08x}.{ext}"
                    if not within(target, destination) or target.exists():
                        raise RuntimeError(f"unsafe or existing NeoXtractor destination: {target}")
                    entry.save_to_file(str(target), decoded=True)
                    transforms = list(getattr(entry, "unwrap_layers", []) or [])
                    rows.append(output_row(base, "NeoXtractor", tool_meta, "ok", target, name=getattr(entry, "filename", None), transforms=transforms))
                except Exception as exc:  # retain one row per observed entry
                    rows.append(output_row(base, "NeoXtractor", tool_meta, "failed", error=repr(exc), name=getattr(upstream_index, "filename", None)))
    except Exception as exc:
        for base in index["entries"][len(rows):]:
            rows.append(output_row(base, "NeoXtractor", tool_meta, "failed", error=repr(exc)))
    finally:
        # Upstream imports may mutate sys.path themselves. Restore the exact
        # caller state instead of removing only our first matching entry.
        sys.path[:] = original_sys_path
    return {
        "tool": "NeoXtractor",
        "tool_metadata": tool_meta,
        "duration_seconds": round(time.time() - started, 3),
        "entry_count": len(rows),
        "status_counts": dict(Counter(row["status"] for row in rows)),
        "entries": rows,
    }


def run_neox_tools(source: Path, destination: Path, index: dict[str, Any], repo: Path) -> dict[str, Any]:
    fresh_dir(destination)
    tool_meta = tool_version(repo)
    started = time.time()
    copied_input = destination / "input" / source.name
    copied_input.parent.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(source, copied_input)
    if copied_input.stat().st_size != source.stat().st_size or sha256_file(copied_input) != sha256_file(source):
        raise RuntimeError("neox_tools input copy did not hash-match source")
    original_sys_path = sys.path.copy()
    sys.path.insert(0, str(repo))
    old_cwd = Path.cwd()
    rows: list[dict[str, Any]] = []
    try:
        module = importlib.import_module("onmyoji_extractor")
        # The upstream function writes <input-without-.npk> beside its input.
        # Running from the run root means optional shell post-processing cannot
        # find a tool-local converter and cannot touch canonical files.
        os.chdir(destination)
        module.unpack(str(copied_input))
        output_dir = copied_input.with_suffix("")
        if not within(output_dir, destination):
            raise RuntimeError("neox_tools output escaped run root")
        by_ordinal: dict[int, Path] = {}
        for path in sorted(output_dir.glob("*")):
            if not path.is_file():
                continue
            stem = path.stem
            try:
                ordinal = int(stem)
            except ValueError:
                continue
            by_ordinal[ordinal] = path
        for base in index["entries"]:
            path = by_ordinal.get(base["ordinal"])
            if path is None:
                rows.append(output_row(base, "neox_tools", tool_meta, "failed", error="upstream extractor produced no output"))
            else:
                rows.append(output_row(base, "neox_tools", tool_meta, "ok", path, name=path.name))
    except Exception as exc:
        for base in index["entries"][len(rows):]:
            rows.append(output_row(base, "neox_tools", tool_meta, "failed", error=repr(exc)))
    finally:
        os.chdir(old_cwd)
        sys.path[:] = original_sys_path
    return {
        "tool": "neox_tools",
        "tool_metadata": tool_meta,
        "copied_input": str(copied_input),
        "copied_input_sha256": sha256_file(copied_input),
        "duration_seconds": round(time.time() - started, 3),
        "entry_count": len(rows),
        "status_counts": dict(Counter(row["status"] for row in rows)),
        "entries": rows,
    }


def run_maintained(source: Path, destination: Path, index: dict[str, Any], repo: Path) -> dict[str, Any]:
    if destination.exists():
        raise RuntimeError(f"maintained parser destination already exists: {destination}")
    started = time.time()
    src_root = repo / "src"
    original_sys_path = sys.path.copy()
    sys.path.insert(0, str(src_root))
    try:
        from asset_extractor.inventory import DEFAULT_LIMITS
        from asset_extractor.pipeline import extract_inputs

        manifest = extract_inputs(
            [str(source)],
            destination,
            profile="nxpk",
            limits=dict(DEFAULT_LIMITS, max_member_bytes=MAX_ENTRY_BYTES, max_total_bytes=MAX_TOTAL_BYTES, max_ratio=MAX_RATIO),
        )
        rows: list[dict[str, Any]] = []
        by_index = {int(item["index"]): item for item in manifest.get("entries", []) if item.get("index") is not None}
        tool_meta = {"repository": str(repo), "version": "asset-extractor-0.2.0", "source_tree_sha256": sha256_json(sorted(str(p.relative_to(repo)) for p in repo.rglob("*.py")))}
        for base in index["entries"]:
            item = by_index.get(base["ordinal"])
            if item is None:
                rows.append(output_row(base, "maintained-parser", tool_meta, "failed", error="maintained parser produced no entry"))
                continue
            path = destination / "extracted" / f"001-{source.stem}" / item["path"]
            rows.append(output_row(base, "maintained-parser", tool_meta, item["status"], path if item["status"] == "ok" else None, error=None if item["status"] == "ok" else item.get("error"), name=item["path"]))
        return {
            "tool": "maintained-parser",
            "tool_metadata": tool_meta,
            "duration_seconds": round(time.time() - started, 3),
            "manifest": manifest,
            "entry_count": len(rows),
            "status_counts": dict(Counter(row["status"] for row in rows)),
            "entries": rows,
        }
    finally:
        sys.path[:] = original_sys_path


def flatten_results(results: dict[str, dict[str, Any]], source: dict[str, Any], run_id: str, index: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tool_name, result in results.items():
        for item in result["entries"]:
            rows.append({
                "schema_version": 1,
                "run_id": run_id,
                "source": source,
                "tool": item["tool"],
                "tool_metadata": item["tool_metadata"],
                "entry": item,
            })
    return rows


def differential(results: dict[str, dict[str, Any]], index: dict[str, Any]) -> dict[str, Any]:
    by_tool = {name: {row["ordinal"]: row for row in result["entries"]} for name, result in results.items()}
    names = list(by_tool)
    comparisons: list[dict[str, Any]] = []
    categories = Counter()
    difference_counts = Counter()
    for base in index["entries"]:
        ordinal = base["ordinal"]
        rows = {name: by_tool[name].get(ordinal) for name in names}
        present = [name for name, row in rows.items() if row is not None]
        boundary_groups = Counter(
            (row["offset"], row["packed_bytes"], row["declared_unpacked_bytes"], row["flags_raw"])
            for row in rows.values()
            if row is not None
        )
        payload_groups = Counter(
            (row["actual_size"], row["output_sha256"])
            for row in rows.values()
            if row is not None and row.get("status") == "ok" and row.get("output_sha256")
        )
        two_boundary = max(boundary_groups.values(), default=0) >= 2
        two_payload = max(payload_groups.values(), default=0) >= 2
        all_success = len(present) == len(names) and all(row.get("status") == "ok" for row in rows.values())
        name_groups = Counter(
            row.get("name")
            for row in rows.values()
            if row is not None and row.get("name") is not None
        )
        name_difference = len(name_groups) > 1
        if name_difference:
            difference_counts["naming"] += 1
        if not all_success and any(row is not None and row.get("status") == "ok" for row in rows.values()):
            difference_counts["one_sided_success"] += 1
        if len(boundary_groups) > 1:
            difference_counts["boundary"] += 1
        if len(payload_groups) > 1:
            difference_counts["payload_sha_or_size"] += 1
        if all_success and len(boundary_groups) == 1 and len(payload_groups) == 1:
            status = "agreement_all"
            categories["agreement_all"] += 1
        elif two_boundary and two_payload:
            status = "agreement_two_or_more"
            categories["agreement_two_or_more"] += 1
        else:
            status = "discrepancy"
            categories["discrepancy"] += 1
        comparisons.append({
            "ordinal": ordinal,
            "payload_id": base["payload_id"],
            "status": status,
            "tools": rows,
            "boundary_groups": [{"key": list(key), "count": count} for key, count in boundary_groups.items()],
            "successful_payload_groups": [{"key": list(key), "count": count} for key, count in payload_groups.items()],
            "name_groups": [{"name": key, "count": count} for key, count in name_groups.items()],
            "name_difference": name_difference,
            "two_or_more_boundary_agreement": two_boundary,
            "two_or_more_payload_agreement": two_payload,
        })
    accepted = categories["agreement_all"] + categories["agreement_two_or_more"]
    return {
        "schema_version": 1,
        "entry_count": len(comparisons),
        "status_counts": dict(categories),
        "difference_counts": dict(difference_counts),
        "gate": {
            "all_three_agree": categories["agreement_all"] == len(comparisons),
            "at_least_two_agree": accepted == len(comparisons),
            "accepted_entries": accepted,
            "unresolved_entries": len(comparisons) - accepted,
        },
        "comparisons": comparisons,
    }


def markdown_report(report: dict[str, Any], source: dict[str, Any], index: dict[str, Any], results: dict[str, dict[str, Any]]) -> str:
    lines = [
        "# Onmyoji qmodel_2409 pilot differential report",
        "",
        f"- Source: `{source['manifest_path']}` ({source['expected_size']} bytes, `{source['expected_sha256']}`)",
        f"- Header: `{index['magic']}`, entries={index['entry_count']}, index_size={index['index_size']}, index_offset={index['index_offset']}",
        f"- Declared unpacked total: {index['declared_total_unpacked_bytes']} bytes",
        "",
        "## Tool results",
        "",
        "| Tool | Commit/version | Entries | Status counts |",
        "|---|---|---:|---|",
    ]
    for name, result in results.items():
        meta = result["tool_metadata"]
        ident = meta.get("commit", meta.get("version", "unknown"))
        lines.append(f"| {name} | `{ident}` | {result['entry_count']} | `{result['status_counts']}` |")
    lines += ["", "## Gate", "", f"- Status counts: `{report['status_counts']}`", f"- Difference counts: `{report.get('difference_counts', {})}`", f"- All-three agreement: `{report['gate']['all_three_agree']}`", "- Naming differences are reported separately from payload/boundary agreement; no unmatched result is guessed or merged.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--canonical-root", type=Path, required=True)
    parser.add_argument("--canonical-manifest", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--neox-root", type=Path, required=True)
    parser.add_argument("--neox-config", type=Path, required=True)
    parser.add_argument("--neox-tools-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    args.run_root = args.run_root.resolve()
    fresh_dir(args.run_root)
    rows = canonical_rows(args.canonical_root.resolve(), args.canonical_manifest.resolve())
    pre = verify_sources(rows, "pre")
    write_json(args.run_root / "source-verification-pre.json", pre)
    if pre["status"] != "ok":
        raise SystemExit("canonical preflight hash verification failed")
    source = args.source.resolve()
    index = parse_index(source)
    write_json(args.run_root / "pilot-index.json", index)

    results: dict[str, dict[str, Any]] = {}
    results["NeoXtractor"] = run_neox(source, args.run_root / "NeoXtractor", index, args.neox_root.resolve(), args.neox_config.resolve())
    results["neox_tools"] = run_neox_tools(source, args.run_root / "neox_tools", index, args.neox_tools_root.resolve())
    results["maintained-parser"] = run_maintained(source, args.run_root / "maintained-parser", index, Path(__file__).resolve().parent)
    write_json(args.run_root / "tool-results.json", results)

    source_info = next(row for row in rows if Path(row["path"]).resolve() == source)
    normalized = flatten_results(results, source_info, args.run_id, index)
    write_json(args.run_root / "normalized-inventory.json", normalized)
    diff = differential(results, index)
    write_json(args.run_root / "differential.json", diff)
    (args.run_root / "differential.md").write_text(markdown_report(diff, source_info, index, results), encoding="utf-8")

    post = verify_sources(rows, "post")
    write_json(args.run_root / "source-verification-post.json", post)
    if post["status"] != "ok":
        raise SystemExit("canonical postflight hash verification failed")
    run_manifest = {
        "schema_version": 1,
        "run_id": args.run_id,
        "created_at_epoch": time.time(),
        "source": source_info,
        "pilot_index": {key: value for key, value in index.items() if key != "entries"},
        "tools": {name: {key: value for key, value in result.items() if key != "entries"} for name, result in results.items()},
        "source_verification": {"pre": str(args.run_root / "source-verification-pre.json"), "post": str(args.run_root / "source-verification-post.json")},
        "differential": str(args.run_root / "differential.json"),
        "safety": {"max_entry_bytes": MAX_ENTRY_BYTES, "max_total_bytes": MAX_TOTAL_BYTES, "max_ratio": MAX_RATIO, "canonical_read_only": True, "extracted_payloads_executed": False},
    }
    write_json(args.run_root / "run-manifest.json", run_manifest)
    print(json.dumps({"run_root": str(args.run_root), "index": index["entry_count"], "tools": {name: result["status_counts"] for name, result in results.items()}, "differential": diff["status_counts"], "source_post": post["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
