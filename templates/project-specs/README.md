# Project specifications

This directory is the canonical source of truth for the project's current durable product and system requirements.

## Suggested contents

Use only the documents the project actually needs. Typical examples:

- `product.md` — purpose, users, outcomes, scope, non-goals;
- `requirements.md` — functional requirements and externally visible behavior;
- `api.md` — externally meaningful API contracts when not generated from another canonical schema;
- `data-model.md` — durable domain/data constraints;
- `ui.md` — user-visible interaction and presentation requirements;
- `non-functional.md` — performance, security, reliability, portability, or operational requirements.

## Rules

- Keep current requirements here; move superseded material to project history when it still has value.
- Architecture documents explain how requirements are implemented and should not become a competing requirements source.
- Issues and task plans describe a unit of work; they do not replace the current specification set.
- Before changing observable behavior, read the relevant specification first.
- If code and specification disagree, surface the conflict and resolve which behavior is intended before treating the task as complete.
- Do not duplicate the same normative requirement across several files unless one location is clearly marked as derived/reference material.

## Index

Add links below to the specification documents that are currently normative for the project.

- <!-- example: [Product](product.md) -->
