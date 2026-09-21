# Codex Software Development Harness

Shared rules are managed from `palladiumailab-collabmAILab/codex-dev-harness`; the pinned revision is recorded in `docs/harness-upstream.md`. Keep project-specific rules in `AGENTS.project.md` or explicitly project-specific skills/docs, and read `AGENTS.project.md` when present.

## Common invariants

- Preserve the requested outcome, explicit constraints, and acceptance criteria.
- Before changing durable product/system behavior, read the relevant `docs/specs/` or existing canonical requirement source; surface conflicts instead of silently choosing one side.
- Treat tests, lint, builds, CI, evaluations, and inspections as evidence, not as substitutes for the requested outcome. Do not weaken checks merely to obtain a pass.
- Keep changes minimal and preserve unrelated work. Do not default to destructive reset/clean/checkout or force push.
- Never expose or commit secrets, private keys, tokens, or unnecessary personal data. Do not deploy, incur charges, delete data, change permissions, or write to external services unless explicitly authorized.
- Read only the nearest instructions and the specifications, code, tests, and configuration needed for the task. Avoid purposeless repository-wide scans and large log dumps.

## Read only when relevant

- Docker / GitHub Actions / Python-Ruff / shared specification layout: `docs/project-baseline.md`
- task contracts / evaluation / optimization semantics: `docs/harness-architecture.md`
- explicit GitHub remote operations: `skills/github-operations/SKILL.md`
- unfamiliar cross-module repository investigation: `skills/repo-research/SKILL.md`
- evaluated iterative agent/workflow optimization: `skills/self-improvement/SKILL.md`
- substantial multi-stage or multi-session handoff: `skills/long-running-work/SKILL.md`

## Model use

- Default to `gpt-5.6-sol / medium` for implementation, architecture, debugging, review, and integration.
- Use `gpt-5.6-luna / max` only for bounded extraction, mechanical transformation, limited exploration, or independent read-only checks.
- Escalate to Sol when the work requires cross-cutting judgment or a bounded Luna attempt fails; do not repeat the same failed cheap path.

Shared files listed in `docs/harness-upstream.md` remain upstream-managed; change common rules in the canonical harness first.
