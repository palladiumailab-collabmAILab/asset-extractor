"""Resolve a stage GIM -> conventional mesh/MTL -> first texture by NeoX path hash.

This reads only extracted files. It is a best-effort resolver: GIM files normally
share a basename with their mesh and material, while MTL texture paths retain the
logical source extension even when the extracted payload is detected as KTX.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SOURCE_TREE = Path(__file__).parent / "NeoXtractor-source-v3.2"
sys.path.insert(0, str(SOURCE_TREE))
from core.npk.npkhash_v1 import mesh_hash  # noqa: E402


def hash_key(path: str) -> str:
    normalized = path.replace("/", "\\").lower()
    return f"{mesh_hash(normalized):08x}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("extracted", type=Path)
    parser.add_argument("--scene", type=Path)
    args = parser.parse_args()

    by_hash: dict[str, list[Path]] = {}
    for path in args.extracted.rglob("*"):
        if path.is_file():
            # NPK extraction preserves a 64-bit signature in many filenames
            # (for example ``index_7d2990233617ab9c.gim``).  The logical NeoX
            # path hash is the low 32 bits, so capture the final eight hex
            # digits regardless of whether the preceding characters include
            # an underscore or another hex digit.
            match = re.search(r"([0-9a-fA-F]{8})$", path.stem)
            if match:
                by_hash.setdefault(match.group(1).lower(), []).append(path)

    scenes = [args.scene] if args.scene else list(args.extracted.rglob("*.scn"))
    results = []
    for scene in scenes:
        text = scene.read_text(encoding="utf-8", errors="ignore")
        for gim_path in re.findall(r'Path\s*=\s*["\']([^"\']+\.gim)["\']', text, re.I):
            base = gim_path[:-4]
            mesh_matches = by_hash.get(hash_key(base + ".mesh"), [])
            mtl_matches = by_hash.get(hash_key(base + ".mtl"), [])
            for mtl in mtl_matches:
                mtl_text = mtl.read_text(encoding="utf-8", errors="ignore")
                refs = re.findall(r'Value\s*=\s*["\']([^"\']+\.(?:png|tga|dds|pvr|ktx))["\']', mtl_text, re.I)
                textures = []
                for ref in refs:
                    textures.extend(by_hash.get(hash_key(ref), []))
                if mesh_matches and textures:
                    results.append(
                        {
                            "logical_gim": gim_path,
                            "mesh": str(mesh_matches[0]),
                            "mtl": str(mtl),
                            "texture_reference": refs[0] if refs else None,
                            "texture": str(textures[0]),
                        }
                    )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if results else 2


if __name__ == "__main__":
    raise SystemExit(main())
