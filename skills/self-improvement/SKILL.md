---
name: self-improvement
description: Optimize an existing agent, prompt, tool, parser, rule set, or workflow by generating bounded candidates and comparing them against a baseline with explicit evaluation criteria. Do not use for a one-off rewrite.
---

# Self-improvement harness

Use this skill only when the user asks to improve an existing agent/workflow through repeated evaluation or optimization.

## Required inputs

Identify before changing the current best state:

- business/task success criterion;
- current baseline and best-so-far artifact;
- optimization examples and separate hold-out evaluation examples;
- exact invariants and semantic/trajectory criteria;
- important failure categories and critical no-regression metrics;
- predeclared acceptance thresholds such as `min_improvement` and `allowed_regression`.

If the evaluation cannot distinguish a candidate from noise, record `unresolved` instead of claiming improvement.

## Workflow

1. **Collect traces** — retain compact successful/failed executions, tool calls, failure category, and relevant provenance. Generalize repeated failures rather than appending one-off prompt patches.
2. **Bound the edit** — declare the component being changed and avoid unrelated refactoring.
3. **Generate alternatives** — preserve structurally different candidates when the failure may require more than a local prompt edit.
4. **Evaluate** — run deterministic checks for exact invariants, then hold-out evaluation. Use model/hybrid graders only where semantic or trajectory quality cannot be represented faithfully by exact checks.
5. **Select** — compare candidates against immutable best-so-far using the predeclared gates. Critical regression rejects; insufficient evidence becomes `unresolved`.
6. **Record** — persist the candidate diff/summary, data versions, experiment provenance, metrics, failure categories, evaluator identity/configuration, sample count, decision, and reason.

## Search strategy

Use the lightest strategy that preserves meaningful alternatives:

- small problem: baseline plus a few candidates;
- broader problem: bounded tournament/best-first search;
- expensive evaluation: cheap deterministic rejection before costly semantic evaluation.

Stop when the improvement threshold is not met, the evaluation budget is exhausted, or no candidate passes the required gates.

## Anti-patterns

- adding one prompt sentence or string replacement for each observed failure;
- evaluating on the examples used to devise the change;
- using an LLM judge for an exact invariant;
- treating model grading as deterministic or leaving its configuration unrecorded;
- overwriting best-so-far before evaluation;
- optimizing one aggregate score while hiding a critical failure-class regression;
- accepting/rejecting on a tiny one-run delta without accounting for evaluation noise.

Cross-cutting record semantics and acceptance rules are defined in `docs/harness-architecture.md`. Executable schemas/validators belong to the contract enforcement layer rather than this skill.
