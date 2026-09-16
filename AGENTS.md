# Asset extraction automation

This repository follows the shared Codex development harness while keeping asset-extraction-specific safety and provenance rules local.

## Operating invariants

- Confirm the requested outcome, change scope, and acceptance criteria before implementation. If an ambiguity can materially change the implementation or completion decision, ask the user instead of silently inventing the goal.
- Treat `docs/specs/` as the canonical home for durable current requirements. Read the relevant specification before changing observable behavior, data contracts, or extraction semantics. If code and specification conflict, surface the conflict rather than silently choosing one.
- Tests, lint, builds, inspections, and rendered artifacts are evidence for acceptance criteria; they are not completion by themselves. Do not weaken tests, fixtures, graders, thresholds, schemas, or acceptance criteria merely to obtain a pass.
- Preserve pre-existing user changes. Do not use destructive Git operations such as `git reset --hard`, `git clean`, or `git checkout --` to discard unrelated work.
- Keep changes small and purpose-scoped. Respect existing layout, naming, dependencies, schemas, and package/tool choices unless the task explicitly requires changing them.
- The canonical development and verification path must be reproducible with Docker. Host execution may be used as a faster path, but host-only success is not sufficient for repository-level completion.
- Maintained Python uses Ruff for both lint and format checks: `ruff check` and `ruff format --check`. Keep orthogonal checks such as mypy, unit tests, schema validation, and domain-specific verification when applicable.
- After changes, review the diff and run checks proportional to the change. If a required check cannot be run, report the reason.
- Never output, commit, or transmit credentials, private keys, tokens, unnecessary personal data, or large proprietary asset corpora.
- Do not deploy, delete data, change permissions, incur charges, force-push, or write to GitHub unless the user explicitly requested that external action.

## Project safety boundary

The project is limited to authorized local APK/OBB/NPK compatibility analysis and asset restoration.

- Do not bypass authentication, DRM, access controls, licensing restrictions, root protections, or application sandboxes.
- Do not execute extracted payloads.
- Treat `input/` as read-only source/provenance data. Never modify source artifacts in place.
- Write every extraction to a new output directory. Do not silently overwrite or reuse an existing run.
- Record source/tool/configuration identity and hashes needed to reproduce or audit a run.
- Make unresolved work and partial success explicit. Required evaluation that is unresolved cannot be reported as `complete`.
- Preserve the run status contract `complete` / `partial` / `failed` and the existing exit-code semantics where defined by the current specification.

## Repository layout

- `input/`: read-only source files and provenance manifests.
- `output/`: generated runs, validation results, and legacy outputs.
- `programs/`: maintained implementation and vendor references.
- `development/`: plans, evidence, fixtures, schemas, tests, and work handoffs.
- `docs/specs/`: canonical durable requirements and links to executable contracts.

## Model and skill routing

- Default implementation, design, debugging, review, and integration: `gpt-5.6-sol / medium`.
- Use `gpt-5.6-luna / max` only for bounded candidate extraction, mechanical transformation, limited exploration, or independent read-only checks. Escalate to Sol instead of repeating a failed bounded attempt.
- `repo-research`: unfamiliar repository areas, complex dependencies, or external specifications.
- `github-operations`: GitHub create/update/push/pull/Issue/PR work explicitly requested by the user.
- `reverse-engineering`: authorized format analysis and evidence-driven compatibility work.
- `long-running-work`: multi-stage or multi-session work requiring compact handoff and explicit partial state.
- `self-improvement`: only when explicitly optimizing an agent/workflow against measurable outcomes; do not use it for ordinary extractor feature work.

GitHub writes are never implied by ordinary local development instructions.
