# Project-specific Codex instructions

## Scope and safety boundary

This project is limited to authorized local APK/OBB/NPK compatibility analysis and asset restoration.

- Do not bypass authentication, DRM, access controls, licensing restrictions, root protections, or application sandboxes.
- Do not execute extracted payloads.
- Treat `input/` as read-only source/provenance data; never modify source artifacts in place.
- Write each extraction to a new output directory rather than silently overwriting or reusing an existing run.
- Record the source, tool/configuration identity, and hashes needed to reproduce or audit a run.
- Preserve the existing `complete` / `partial` / `failed` run-status contract and exit-code semantics where defined by the current specification.
- Required evaluation that remains unresolved cannot be reported as complete.
- Use `skills/reverse-engineering/SKILL.md` only for authorized format/compatibility analysis.

## Repository layout

- `input/`: read-only source files and provenance manifests.
- `output/`: generated runs, validation results, and legacy outputs.
- `programs/`: maintained implementation and vendor references.
- `development/`: plans, evidence, fixtures, schemas, tests, and work handoffs.
- `docs/specs/`: canonical durable requirements and executable-contract links.
