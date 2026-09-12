---
name: reverse-engineering
description: Analyze the observable behavior of an authorized legacy, opaque, binary, or protocol component for compatibility, debugging, or defensive purposes. Do not use for ordinary code reading.
metadata:
  short-description: Trace authorized black-box behavior
---

# Authorized reverse engineering

Use this skill only when the user has a legitimate reason to understand an opaque or legacy component, protocol, file format, binary interface, or black-box behavior. Keep the work focused on interoperability, migration, diagnosis, testing, or defense.

Do not bypass access controls, licensing, authentication, or encryption; extract secrets; target systems without authorization; or produce persistence, evasion, destructive, or intrusion instructions. If the requested goal crosses that boundary, stop and state the safe scope that remains.

## Workflow

1. Define the authorized target, allowed inputs, allowed tools, environment, and exact behavior to explain. Separate local artifacts from anything that would contact a third-party system.
2. Preserve evidence before changing anything: version, hashes where appropriate, command lines, fixtures, observed outputs, timestamps, and environment assumptions. Redact credentials and personal data.
3. Observe before inferring. Build a small, reproducible matrix of inputs, outputs, errors, state transitions, timing only when relevant, and side effects. Use the smallest fixture that distinguishes competing hypotheses.
4. Trace static structure and dynamic behavior independently. Mark each conclusion as `fact`, `strong inference`, or `unknown`; attach a source location, trace, or reproducible experiment to facts.
5. When parallel work helps, delegate independent read-only lanes such as format/protocol observation and static call-graph tracing. Use Luna for repetitive collection and Sol for synthesis or difficult interpretation. Keep the parent agent responsible for the final model and any edits.
6. Convert important observations into regression fixtures or characterization tests only when the user asks for implementation or the repository's workflow requires them. Do not alter the target merely to make the observation easier.

## Output

Provide a concise behavior contract:

- target and authorization assumptions;
- input/output and error matrix;
- state, ordering, and side-effect rules;
- evidence and reproducibility commands;
- compatibility constraints and open questions;
- safe next implementation or test step.

Prefer a minimal reproducer over a broad dump. Never include secrets, private keys, raw credentials, or unnecessary personal data in notes or commits.
