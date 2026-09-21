---
name: repo-research
description: Map an unfamiliar repository before code changes when the task requires tracing entry points across modules, cross-module flows, legacy boundaries, or an external specification. Do not use for a known-file small edit.
metadata:
  short-description: Investigate a codebase before coding
---

# Repository research

Use this skill only when implementation depends on understanding an unfamiliar codebase, a cross-module flow, a legacy boundary, or an external specification. The default output is a read-only, evidence-backed map; do not modify product code unless the user separately asks for it.

## Workflow

1. Restate the research question and the decision it must support. Keep the scope bounded.
2. Read the nearest `AGENTS.md`, `README.md`, package manifests, build configuration, and test entry points that are relevant to the question.
3. Use `rg --files` and targeted `rg` searches to locate entry points, symbols, configuration keys, data models, adapters, and tests. Follow the call path from an executable or public boundary instead of reading the whole repository.
4. Record facts separately from hypotheses. Cite `path:line` evidence for important claims and include the command or test that can confirm a behavior.
5. If the repository is broad, delegate at most two independent, read-only lanes: one for runtime/module flow and one for tests/configuration/dependencies. Give each lane a file or directory boundary and require a short result with evidence only.
6. Stop when the target decision is supported. Report unknowns instead of expanding the search indefinitely.

## Output

Return a compact handoff with:

- the likely entry point and end-to-end flow;
- the smallest set of files that should change;
- relevant conventions, dependencies, and test commands;
- facts with `path:line` evidence;
- assumptions, unknowns, and the next implementation decision.

Do not return full files, large logs, duplicated summaries, or speculative redesigns. Do not install packages, contact external services, or alter repository state as part of read-only research.
