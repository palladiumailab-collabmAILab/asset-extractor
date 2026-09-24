# Codex harness upstream

The shared Codex development harness in this repository is sourced from:

- repository: `palladiumailab-collabmAILab/codex-dev-harness`
- source revision: `d8b465a53f5c22c81803a1ddb5fdc9ddfa596210`

## Ownership

The upstream repository is the canonical source for all shared harness content. Files listed below are upstream-managed and must not be edited independently in this downstream repository. Project-specific rules belong in `AGENTS.project.md` or other explicitly project-specific files.

When a shared rule needs to change:

1. change and validate it in `codex-dev-harness`;
2. record the new upstream revision here;
3. synchronize the managed files from that revision;
4. keep downstream-only changes out of the managed files.

## Upstream-managed files

- `AGENTS.md`
- `docs/project-baseline.md`
- `docs/harness-architecture.md`
- `docs/testing-governance.md`
- `skills/repo-research/SKILL.md`
- `skills/github-operations/SKILL.md`
- `skills/self-improvement/SKILL.md`
- `skills/long-running-work/SKILL.md`
- `templates/codex-progress.md`
- `templates/project-specs/README.md`

## Applied overlays

- testing governance / Sol-Luna role split: `4e0ad32b680451610b3f601e982cc5b04956bf1b`
