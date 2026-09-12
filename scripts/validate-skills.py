from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml


NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def validate_skill(skill_directory: Path) -> list[str]:
    errors: list[str] = []
    skill_file = skill_directory / "SKILL.md"

    if not skill_file.is_file():
        return [f"{skill_directory}: SKILL.md is missing"]

    try:
        text = skill_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [f"{skill_file}: file must be UTF-8"]

    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return [f"{skill_file}: YAML frontmatter must start on the first line"]

    try:
        closing_index = lines.index("---", 1)
    except ValueError:
        return [f"{skill_file}: YAML frontmatter closing delimiter is missing"]

    try:
        metadata = yaml.safe_load("\n".join(lines[1:closing_index]))
    except yaml.YAMLError as error:
        return [f"{skill_file}: invalid YAML frontmatter: {error}"]

    if not isinstance(metadata, dict):
        return [f"{skill_file}: YAML frontmatter must be a mapping"]

    name = metadata.get("name")
    description = metadata.get("description")

    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        errors.append(f"{skill_file}: name must use lowercase letters, digits, and hyphens")
    elif len(name) > 63:
        errors.append(f"{skill_file}: name must be shorter than 64 characters")
    elif name != skill_directory.name:
        errors.append(f"{skill_file}: name must match directory {skill_directory.name!r}")

    if not isinstance(description, str) or not description.strip():
        errors.append(f"{skill_file}: description must be a non-empty string")

    body = "\n".join(lines[closing_index + 1 :]).strip()
    if not body:
        errors.append(f"{skill_file}: instruction body is empty")

    return errors


def main() -> int:
    skills_root = Path(sys.argv[1] if len(sys.argv) > 1 else "skills")
    if not skills_root.is_dir():
        print(f"skills directory was not found: {skills_root}", file=sys.stderr)
        return 1

    skill_directories = sorted(path for path in skills_root.iterdir() if path.is_dir())
    if not skill_directories:
        print(f"no skill directories were found: {skills_root}", file=sys.stderr)
        return 1

    errors = [error for directory in skill_directories for error in validate_skill(directory)]
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    print(f"Validated {len(skill_directories)} skill(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
