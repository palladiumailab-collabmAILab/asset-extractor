# Harness quality audit — 2026-09-16

## Baseline

Reference: `palladiumailab-collabmAILab/codex-dev-harness@25a3929` (`main`) as reviewed on 2026-09-16.

The 2026-09-12 audit remains a historical point-in-time result. Its 96/100 score is not reused as a current score because the shared harness has since added or clarified task contracts, canonical specifications, Docker reproducibility, Ruff formatting, model routing, additional skills, and GitHub Actions as the canonical remote quality gate.

## Gaps found before the initial 2026-09-16 sync

1. Root `AGENTS.md` preserved project safety rules but omitted the current shared task/acceptance contract and model/skill routing.
2. `long-running-work` and `self-improvement` were absent from the local skill set.
3. Durable requirements had no explicit canonical source; plans, README content, schemas, evidence, and progress records coexisted without a single requirements root.
4. Docker validation covered only skill validation rather than the maintained Python test/lint/type/schema path.
5. CI ran `ruff check` but not `ruff format --check`.
6. The old audit did not distinguish its historical baseline from the current harness contract.

## Decisions and applied changes

### Root instructions

`AGENTS.md` keeps cross-task invariants plus asset-extraction-specific safety/provenance rules. It explicitly requires:

- outcome/scope/acceptance criteria before implementation;
- user clarification when ambiguity materially changes implementation or completion;
- `docs/specs/` review for requirement-sensitive work;
- acceptance evidence rather than green-check completion shortcuts;
- no unrequested feature/dependency/integration/large-refactor expansion;
- preservation of unrelated work;
- targeted context loading rather than purposeless repository-wide scans;
- Docker reproducibility;
- Ruff lint and format gates;
- GitHub Actions as the canonical remote quality gate;
- explicit GitHub authorization;
- Sol/Luna and skill routing;
- proportional verification and avoidance of non-progress validation loops.

### Skills

- `long-running-work`: adopted because extraction/reconstruction work can be multi-stage, partially successful, and multi-session. The local variant uses the existing `development/work/codex-progress.md` handoff location.
- `self-improvement`: adopted but explicitly gated to measurable agent/workflow optimization. It is not a default extractor feature-development procedure.
- `repo-research` and `reverse-engineering`: remain byte-for-byte aligned with the shared harness at this review point.
- `github-operations`: synchronized to the rebuilt harness version that treats local/Docker checks as preflight and requires verification of expected GitHub Actions checks before claiming remote completion.

### Canonical specification

`docs/specs/README.md` remains the durable current requirement root. It separates current requirements from implementation plans, progress state, evidence/history, and operator documentation. Existing JSON Schemas remain the executable field-level contracts.

### Docker and quality gates

A root `Dockerfile` defines the canonical maintained-Python verification environment. Its default command runs:

- skill validation;
- branch-coverage unit tests with the existing 55% threshold;
- `ruff check`;
- `ruff format --check`;
- mypy;
- JSON-Schema validation.

`.dockerignore` excludes Git metadata, raw inputs, generated outputs, caches, and vendor payloads from the build context.

`scripts/validate-harness.ps1` uses the Docker image by default. `-SkipDocker` remains a fast host-only path and runs the equivalent Python checks directly.

GitHub Actions validates repository invariants and the pre-commit hook, then builds and runs the canonical Docker validation image. The workflow is triggered for pull requests and pushes, so it satisfies the rebuilt harness requirement for PR and default-branch remote gating without a workflow change.

## Rebuilt-harness delta applied after the initial sync

The rebuilt shared harness commit `25a3929` makes GitHub Actions an explicit canonical quality gate rather than merely another validator. This repository already had the required executable CI path, so the synchronization changes policy and operator guidance rather than duplicating or weakening the workflow:

- root `AGENTS.md` now requires expected GitHub Actions checks to pass before remote completion is claimed;
- the standard workflow explicitly separates local/Docker preflight from remote CI verification;
- `skills/github-operations/SKILL.md` now requires CI verification after GitHub writes and treats missing CI as a project-quality gap;
- no branch-protection or ruleset setting is changed here because repository-administration changes remain a separate explicit action under the shared baseline.

## Preserved project-specific invariants

The update intentionally retains and strengthens the existing constraints that:

- only authorized local compatibility analysis/restoration is in scope;
- source artifacts are immutable;
- extracted payloads are never executed;
- authentication/DRM/access controls are not bypassed;
- every run writes to a new output directory;
- provenance and hashes are retained;
- `complete` / `partial` / `failed` remain distinct and unresolved required evaluation cannot become `complete`.

## Verification status

Repository changes are reviewable on a dedicated branch. The definitive executable verification result is the GitHub Actions run for the resulting pull request; this audit does not claim success solely from configuration inspection.
