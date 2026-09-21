from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MACHINE_SPECIFIC_PATH = re.compile(r"(?i)(?:\b[A-Z]:[\\/]+Users[\\/]+|(?<!\w)/(?:Users|home)/)")


def canonical_documents() -> list[Path]:
    candidates = [ROOT / "README.md", ROOT / "programs/README.md"]
    candidates.extend((ROOT / "docs").rglob("*.md"))
    candidates.extend((ROOT / "development").rglob("*.md"))
    return sorted(
        path
        for path in candidates
        if path.is_file()
        and not {
            "development",
            "evidence",
            "history",
        }.issubset(path.relative_to(ROOT).parts)
    )


def main() -> int:
    errors: list[str] = []
    for path in canonical_documents():
        relative = path.relative_to(ROOT)
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if MACHINE_SPECIFIC_PATH.search(line):
                errors.append(f"{relative}:{line_number}: machine-specific absolute path")

    if errors:
        print("\n".join(errors))
        return 1

    print(f"Validated canonical documentation paths in {len(canonical_documents())} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
