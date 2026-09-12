"""Deduplicate, classify, and convert decoded texture assets.

Game container textures are read-only. KTX/PVR/DDS payloads are converted to
PNG when the bundled decoder supports them; already-standard image files are
copied as reusable native assets. A SHA-256 manifest retains all duplicate
source paths and every failure reason.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parent
SOURCE_TREE = TOOL_ROOT / "NeoXtractor-source-v3.2"
sys.path.insert(0, str(SOURCE_TREE))
from core.images import convert_image  # noqa: E402

CONVERT_EXTENSIONS = {".ktx", ".ktx2", ".pvr", ".astc", ".dds"}
NATIVE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tga", ".bmp"}


def digest_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def convert_one(task: tuple[str, str, str, str, bool]) -> dict:
    digest, source_text, output_text, mode, resume = task
    source = Path(source_text)
    output = Path(output_text)
    if resume and output.is_file() and output.stat().st_size > 0:
        return {"sha256": digest, "source": source_text, "output": output_text, "status": "existing", "mode": mode}
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(output.name + f".tmp.{os.getpid()}")
        if mode == "native_reusable":
            temporary.write_bytes(source.read_bytes())
        else:
            image = convert_image(source.read_bytes(), source.suffix.lower().lstrip("."))
            if image is None:
                raise RuntimeError("decoder returned no image")
            image.save(temporary, "PNG")
        temporary.replace(output)
        return {"sha256": digest, "source": source_text, "output": output_text, "status": "converted", "mode": mode, "bytes": output.stat().st_size}
    except Exception as exc:  # inventory must retain every failed payload
        return {"sha256": digest, "source": source_text, "output": None, "status": "failed", "mode": mode, "error_type": type(exc).__name__, "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=max(1, min(4, (os.cpu_count() or 2) // 2)))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    paths = sorted(
        {path.resolve() for root in args.roots for path in root.resolve().rglob("*") if path.is_file() and path.suffix.lower() in CONVERT_EXTENSIONS | NATIVE_EXTENSIONS},
        key=lambda path: str(path).lower(),
    )
    sources_by_digest: dict[str, list[str]] = defaultdict(list)
    representatives: dict[str, Path] = {}
    sizes: dict[str, int] = {}
    for index, path in enumerate(paths, 1):
        digest, size = digest_file(path)
        sources_by_digest[digest].append(str(path))
        representatives.setdefault(digest, path)
        sizes[digest] = size
        if index % 5000 == 0:
            print(f"[hash] {index}/{len(paths)} unique={len(representatives)}", flush=True)

    digests = sorted(representatives)
    if args.limit > 0:
        digests = digests[: args.limit]
    output = args.output.resolve()
    tasks = []
    for digest in digests:
        source = representatives[digest]
        ext = source.suffix.lower()
        mode = "native_reusable" if ext in NATIVE_EXTENSIONS else "decoded_png"
        out_ext = ext if mode == "native_reusable" else ".png"
        folder = "native" if mode == "native_reusable" else "png"
        filename = f"{digest[:16]}__{source.stem}{out_ext}"
        tasks.append((digest, str(source), str(output / folder / filename), mode, args.resume))

    results = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=max(1, args.workers)) as executor:
        for index, result in enumerate(executor.map(convert_one, tasks, chunksize=8), 1):
            results.append(result)
            if index % 1000 == 0:
                failed = sum(item["status"] == "failed" for item in results)
                print(f"[convert] {index}/{len(tasks)} failed={failed}", flush=True)

    manifest = {
        "schema_version": 1,
        "source_policy": "read-only",
        "roots": [str(root.resolve()) for root in args.roots],
        "files_discovered": len(paths),
        "unique_payloads_discovered": len(representatives),
        "unique_payloads_selected": len(tasks),
        "workers": max(1, args.workers),
        "counts": {status: sum(item["status"] == status for item in results) for status in ("converted", "existing", "failed")},
        "assets": [
            {**result, "source_bytes": sizes[result["sha256"]], "duplicate_source_paths": sources_by_digest[result["sha256"]]}
            for result in results
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "texture_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    failures = [item for item in manifest["assets"] if item["status"] == "failed"]
    (output / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[summary] {manifest['counts']}", flush=True)
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
