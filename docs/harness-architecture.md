# Harness architecture

The harness separates always-on instructions, conditional task skills, cross-cutting contracts, project baselines, and mechanical validation. This follows the broad OpenAI Harness Engineering principle of keeping the always-on instruction surface small and promoting stable invariants into repository-local checks.

## Layers

1. **Operating rules — `AGENTS.md`**
   - only invariants and routing that apply to ordinary work.
2. **Task skills — `skills/*/SKILL.md`**
   - detailed procedures loaded only when their trigger conditions apply.
3. **Project baseline — `docs/project-baseline.md`**
   - reusable defaults such as canonical specifications, Docker reproducibility, and Python/Ruff quality gates without forcing project-specific architecture.
4. **Cross-cutting contracts — this document / schemas**
   - task goals and acceptance, execution provenance, evaluation decisions, design source-of-truth, optimization records.
5. **Mechanical enforcement — `scripts/`, `tests/`, CI**
   - checks stable invariants without relying on model judgment.

## Project specification source

For target repositories, durable current product/system requirements should have one canonical repository-local home. The harness convention is `docs/specs/` unless the project already has an equivalent single source of truth.

Specifications define **what must be true**. Architecture documents define **how the system is structured**. Issues and progress files define **what is being changed now**. Historical records explain superseded decisions. Do not let these roles collapse into one large instruction file.

Before a requirement-sensitive implementation or design change, load the relevant specification rather than the entire documentation tree. If code and specification conflict, surface the conflict instead of silently treating either source as authoritative without resolving currency.

## Task contract

A task is defined by the requested outcome and the acceptance criteria that distinguish success from merely performing work around it.

Before implementation:

- state the requested outcome in one concise form;
- identify the required acceptance criteria and how each can be validated;
- if an ambiguity can materially change the implementation or the completion decision, ask the user to clarify it instead of silently choosing a goal;
- only make an assumption without clarification when the ambiguity cannot materially change the result, and surface the assumption when it matters to review.

Verification evidence is not the same as task progress or task completion. Tests, lint, type checks, builds, inspections, screenshots, measurements, and model-grader results are evidence for a criterion. They imply completion only when they actually establish the requested outcome.

The completion contract therefore requires:

- every required acceptance criterion to have relevant evidence before the task is reported complete;
- `checks green / objective unmet` to remain incomplete rather than being converted into success;
- tests, fixtures, golden outputs, graders, thresholds, or acceptance criteria not to be weakened merely to obtain a pass; a legitimate specification correction must be explicit and justified against the requested behavior;
- repeated verification with no material implementation, artifact, or decision change to count as non-progress; after bounded repetition, change strategy, surface the blocker, or request missing criteria;
- visual, UI, semantic, or otherwise non-unit-testable outcomes to use artifact-level evidence such as rendered output, reference comparison, domain metrics, or a structured manual check instead of substituting unrelated green tests.

For reviewable work, preserve a concise mapping of `criterion -> implementation/change -> evidence`. The mapping may live in a task record, progress file, PR description, or final report; it should not require duplicating full logs.

## Execution result

A long-running or multi-stage workflow should distinguish `complete`, `partial`, and `failed`, and retain enough input/output identity and provenance to reproduce or audit the result.

Typical provenance may include:

- input/output path, size, digest;
- tool/runtime/configuration;
- model and reasoning effort when applicable;
- harness/dataset version;
- attempt/sample count;
- token, time, and cost metadata when available;
- optional provider session/turn/artifact references.

A workflow must not report `complete` when required evaluation is unresolved, when verified inputs/outputs changed unexpectedly, or when the task contract still has an unmet required criterion.

## Evaluation result

Evaluation is separate from execution. Record raw measurements before the acceptance decision.

The evaluation contract should capture:

- primary and secondary metrics;
- failure categories;
- predeclared thresholds such as `min_improvement` and `allowed_regression`;
- critical no-regression metrics/failure classes;
- sample count and uncertainty where relevant;
- evaluator type, version, and configuration;
- task-level criterion identifiers and evidence references when the evaluation is used to decide task completion;
- `accept`, `reject`, or `unresolved` decision.

Use deterministic checks for exact invariants. Use model/hybrid graders when semantic or trajectory quality would be lost by reducing the criterion to an exact check. A small stochastic score delta is not evidence of improvement by itself.

## Canonical design source

For schema-first work, keep one structured source of truth rather than independently editing diagrams, API types, DB schema, and UI models. Derived artifacts should identify the source version used to generate them.

## Optimization record

Self-improvement operates on bounded candidates rather than mutating best-so-far in place. Each candidate should retain:

- parent candidate/baseline identity;
- bounded change scope and summary/diff;
- optimization and hold-out data versions;
- evaluation result and experiment provenance;
- acceptance reason.

Best-so-far changes only after required gates pass. Rejected and unresolved candidates remain traceable when needed for reproducibility.

## Change gate

Before adopting an agent-generated improvement:

1. record baseline and best-so-far;
2. define the target failure mode, change scope, objective, and acceptance thresholds;
3. generate one or more reviewable candidates;
4. run deterministic checks first;
5. evaluate on data not used to propose the change;
6. apply predeclared regression and improvement gates;
7. return `unresolved` when evidence is insufficient;
8. update best-so-far only after all required gates pass;
9. preserve the evidence needed to reproduce the decision.

Iteration count is not evidence of improvement.

## Enforcement

Prose defines semantics; stable invariants should move into versioned schemas, validators, fixtures/tests, and CI. `AGENTS.md` should not duplicate those mechanics. Task-level criterion/evidence linkage belongs in the same executable contract layer as execution/evaluation records so that local prompt wording cannot redefine completion on its own.
