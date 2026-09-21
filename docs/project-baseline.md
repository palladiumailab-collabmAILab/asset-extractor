# Project baseline

This document defines the reusable project-level defaults that sit between the global harness rules and project-specific architecture.

The baseline is intentionally small. It standardizes reproducibility, GitHub CI, Python quality gates, and the location of durable specifications without forcing one Web framework, repository layout, database, or service topology.

## Upstream-managed harness

The reusable harness is owned by `palladiumailab-collabmAILab/codex-dev-harness`. A downstream repository may add project-specific instructions, specifications, skills, validation commands, and architecture rules, but it must not independently rewrite copied common harness content.

For downstream repositories:

- record the pinned upstream revision and managed file set in `docs/harness-upstream.md`;
- keep shared `AGENTS.md`, shared baseline/architecture docs, generic skills, and shared templates synchronized from the upstream revision;
- put repository-specific instructions in `AGENTS.project.md` or other clearly project-specific files;
- when a common rule needs to change, change and validate it upstream first, then sync the downstream copy;
- do not weaken or fork common rules under the label of a project-specific change unless the rule is genuinely project-specific.

This ownership rule prevents shared harness behavior from drifting independently across repositories.

## Canonical specifications

When a project has durable product or system requirements, keep the current specification set under `docs/specs/`.

Use that directory as the canonical source for **what the system is required to do**. Before changing observable behavior, data contracts, external interfaces, or other requirement-sensitive behavior, read the relevant specification first.

Keep responsibilities separate:

- `docs/specs/`: current requirements and externally meaningful behavior;
- architecture/design documents: how the system is structured to satisfy those requirements;
- issues/tasks/progress files: the current unit of work;
- `docs/history/` or equivalent: superseded decisions, audits, and historical records.

If implementation and the current specification disagree, surface the conflict. Do not silently redefine the specification to match the code or change the code merely to match a stale document without resolving which source is current.

Use `templates/project-specs/README.md` as a starting index when a repository does not already have an equivalent canonical specification location. Existing project conventions may be retained when they already provide a clear single source of truth; do not create two competing specification roots.

## Docker baseline

Executable software projects must provide a Docker-based path that reproduces the environment needed to develop and verify the software.

The baseline requires:

- dependencies needed by the canonical verification path can be installed in the containerized environment;
- required lint, format-check, test, and build steps can be run from that environment when they apply;
- the application or primary executable path can be run in Docker when runtime execution is part of the project;
- host execution may be used as a faster developer path, but host-only success is not the canonical reproducibility guarantee.

Do not require Docker Compose for a single-container project. Use Compose or another orchestration layer only when multiple services need coordinated startup.

Do not infer a microservice architecture from the Docker requirement. A monolith, full-stack framework, worker, CLI, API service, or multi-service application can all satisfy the baseline.

## GitHub CI baseline

For executable software hosted on GitHub, GitHub Actions is the canonical remote quality gate.

The repository must provide a workflow that runs for pull requests and for pushes to the default branch. The workflow should execute the checks that are mechanically meaningful for that project, including as applicable:

- lint and format checks;
- automated tests;
- static type checks;
- application, package, or container build verification;
- repository invariants and domain-specific validators;
- existing security or dependency checks that are already part of the project's canonical validation path.

Local and Docker-based checks are preflight evidence, not a substitute for the remote gate. When work is pushed or proposed through a pull request, do not treat it as complete until the expected GitHub Actions checks pass. If a required workflow is missing, cannot run because of repository infrastructure, or fails for an external reason, report that state explicitly rather than claiming remote verification succeeded.

Do not weaken CI only to obtain a green result. Do not add `continue-on-error`, skip relevant tests, reduce coverage or validation thresholds, or remove required checks solely to make a change mergeable.

When repository permissions and project policy allow it, protect the default branch or use a ruleset so the canonical workflow checks are required before merge. Repository settings remain an explicit GitHub administration action; do not change them without authorization.

## Python baseline: Ruff

Every repository containing maintained Python code uses Ruff as the standard lint and format gate, including existing repositories.

At minimum, the canonical validation path and GitHub Actions run:

```text
ruff check ...
ruff format --check ...
```

Configuration belongs in the target repository, normally in `pyproject.toml`. The target Python version, line length, selected lint families, exclusions, and generated-code handling remain project-local decisions.

When an existing project uses overlapping tools, converge their overlapping responsibilities on Ruff instead of retaining duplicate permanent gates without a reason. Typical overlap includes Flake8, isort, pyupgrade, and Black.

Ruff does not replace orthogonal checks. Keep tools such as pytest, mypy, pyright, security scanners, or domain-specific validators when the project needs them, and run them in GitHub Actions when they are part of the project's canonical merge gate.

Migration of an existing project should be reviewable. Do not combine a broad whole-repository reformat with an unrelated feature change unless that migration is itself the requested task.

## Architecture remains project-specific

This baseline does not require physical separation such as:

```text
frontend/
backend/
```

A separate frontend/backend service layout, a full-stack framework, a monorepo, a single service, or another architecture may all be appropriate.

The harness still expects responsibilities and trust boundaries to be understandable, but their physical layout is a project design decision. Framework, database, transport, deployment topology, state management, and inference placement are not universal defaults unless a separate project rule says otherwise.

## Instruction hierarchy

Apply guidance by scope rather than accumulating every rule into one always-on prompt:

1. root `AGENTS.md`: durable cross-project invariants and routing;
2. scoped `AGENTS.md` / task skills: subsystem- or task-specific operating guidance;
3. `docs/specs/`: current required behavior;
4. architecture/configuration: project-specific implementation choices;
5. tests, linters, validators, and CI: mechanically enforceable constraints.

More specific repository-local instructions may refine the baseline, but should not silently weaken explicit user requirements or safety constraints.
