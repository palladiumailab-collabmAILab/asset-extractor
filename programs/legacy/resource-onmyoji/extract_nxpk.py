"""Non-destructive NXPK extractor for the locally captured Onmyoji assets.

The source NPK files are never modified. Decoded entries are written below the
requested output directory with signature-based names when the archive does not
contain a filename table.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from core.npk.class_types import NPKEntryDataFlags, NPKReadOptions
from core.npk.npk_file import NPKFile


WANTED_EXTENSIONS = {
    "mesh",
    "gltf",
    "glb",
    "obj",
    "pmx",
    "png",
    "jpg",
    "jpeg",
    "dds",
    "pvr",
    "ktx",
    "ktx2",
    "ktx_low",
    "astc",
    "cbk",
    "psd",
    "tga",
    "bmp",
    "atlas",
    "xml",
    "skeleton",
    "skeletonextra",
    "skeletonrig",
    "animconfig",
}

WANTED_CATEGORIES = {"Mesh", "Texture"}
STAGE_EXTENSIONS = {"scn", "mtl", "gim"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--key", type=int, default=150)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--all", action="store_true", dest="extract_all")
    parser.add_argument(
        "--stage",
        action="store_true",
        help="also extract scene/material/image-map references (.scn/.mtl/.gim)",
    )
    return parser.parse_args()


def safe_name(index: int, signature: int, extension: str) -> str:
    ext = extension or "bin"
    return f"{index:06d}_{signature:016x}.{ext}"


def process(
    source: Path,
    output_root: Path,
    key: int,
    limit: int,
    extract_all: bool,
    extract_stage: bool,
) -> dict:
    result = {
        "source": str(source),
        "output": str(output_root),
        "decryption_key": key,
        "header": {},
        "entry_count": 0,
        "extension_counts": {},
        "category_counts": {},
        "extracted": [],
        "errors": [],
    }

    archive = NPKFile(str(source), NPKReadOptions(decryption_key=key))
    result["header"] = {
        "file_type": getattr(archive, "file_type", None).name
        if getattr(archive, "file_type", None) is not None
        else None,
        "file_count": archive.file_count,
        "var1": archive.var1,
        "encrypt_mode": archive.encrypt_mode,
        "hash_mode": archive.hash_mode,
        "index_offset": archive.index_offset,
        "info_size": archive.info_size,
    }
    result["entry_count"] = len(archive.indices)
    extension_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    destination = output_root / source.stem
    destination.mkdir(parents=True, exist_ok=True)

    with source.open("rb") as file_handle:
        for index in range(len(archive.indices)):
            if limit and index >= limit:
                break
            try:
                archive.load_entry(index, file_handle)
                entry = archive.entries[index]
                extension = (entry.extension or "bin").lower()
                category = getattr(entry.category, "value", str(entry.category))
                extension_counts[extension] += 1
                category_counts[category] += 1
                failed_flags = entry.data_flags & (
                    NPKEntryDataFlags.ERROR | NPKEntryDataFlags.ENCRYPTED
                )
                if failed_flags:
                    result["errors"].append(
                        {
                            "index": index,
                            "filename": entry.filename,
                            "extension": extension,
                            "flags": int(entry.data_flags),
                            "error": "NeoXtractor marked this entry as failed or still encrypted",
                        }
                    )
                    continue

                should_extract = (
                    extract_all
                    or category in WANTED_CATEGORIES
                    or extension in WANTED_EXTENSIONS
                    or (extract_stage and extension in STAGE_EXTENSIONS)
                )
                if should_extract:
                    filename = safe_name(index, entry.file_signature, extension)
                    output_path = destination / category / filename
                    entry.save_to_file(str(output_path), decoded=True)
                    result["extracted"].append(
                        {
                            "index": index,
                            "signature": f"{entry.file_signature:016x}",
                            "filename": entry.filename,
                            "extension": extension,
                            "category": category,
                            "size_bytes": len(entry.data),
                            "path": str(output_path),
                            "compression_flag": int(entry.zip_flag),
                            "encryption_flag": int(entry.encrypt_flag),
                            "flags": int(entry.data_flags),
                        }
                    )
            except Exception as exc:  # keep processing other entries
                result["errors"].append({"index": index, "error": repr(exc)})

    result["extension_counts"] = dict(extension_counts)
    result["category_counts"] = dict(category_counts)
    (destination / "extraction_manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    summaries = []
    for source in args.inputs:
        if not source.is_file():
            print(f"[skip] missing: {source}", file=sys.stderr)
            continue
        print(f"[read] {source}", flush=True)
        summary = process(
            source,
            args.output,
            args.key,
            args.limit,
            args.extract_all,
            args.stage,
        )
        summaries.append(summary)
        print(
            f"[done] entries={summary['entry_count']} "
            f"extracted={len(summary['extracted'])} errors={len(summary['errors'])}",
            flush=True,
        )
    (args.output / "run_manifest.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0 if summaries and all(not item["errors"] for item in summaries) else 2


if __name__ == "__main__":
    raise SystemExit(main())
