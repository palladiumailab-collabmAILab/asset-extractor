# Canonical specifications

This directory is the canonical source of durable, current requirements for `asset-extractor`.

Implementation notes, plans, progress logs, evidence, and historical audits may explain how or why the system evolved, but they do not redefine the current requirements here. If implementation and this specification disagree, surface the conflict before changing behavior.

## Scope and safety

The maintained extractor supports authorized local compatibility analysis and asset restoration for APK/OBB/NPK and related archive/resource formats.

Required safety properties:

- never modify source artifacts in place;
- never bypass authentication, DRM, access controls, licensing restrictions, root protections, or application sandboxes;
- never execute extracted payloads;
- reject unsafe archive paths, symlinks, path collisions, unsupported flags, and invalid bounds according to the maintained validators;
- bound extraction by entry count, individual size, total size, and decompression limits where the backend exposes those controls;
- keep proprietary raw asset corpora and credentials out of Git.

## Run contract

Every extraction or restoration run must:

- write to a new output directory rather than silently overwriting or reusing an existing run;
- retain sufficient source, tool, configuration, and output identity to reproduce or audit the result;
- verify source immutability where the current run type supports before/after hashing;
- distinguish `complete`, `partial`, and `failed` rather than converting unresolved or best-effort results into success;
- preserve the documented exit-code semantics of each maintained CLI/run type;
- fail closed when required evaluation is unresolved or input/output integrity cannot be established.
- treat omitted optional pipeline stages as `skipped` without degrading the overall run; once an optional stage is configured, it is required for that run;
- report a required upstream failure as `failed`, mark dependent required stages `blocked`, and never convert required `partial`/`failed`/`blocked` work into `complete`.

## Executable contracts

The following schemas are authoritative mechanical contracts for their respective artifacts:

- `development/schemas/run-manifest.schema.json`: generic extraction run manifest;
- `development/schemas/minimal-restore-test.schema.json`: minimal restoration test result;
- `development/schemas/pipeline-config.schema.json`: unified pipeline configuration;
- `development/schemas/pipeline-manifest.schema.json`: unified pipeline result;
- `development/schemas/netease-backend-manifest.schema.json`: NetEase backend result;
- `development/schemas/backend-runs-manifest.schema.json`: multi-backend execution record;
- `development/schemas/bluestacks-snapshot.schema.json`: authorized BlueStacks snapshot provenance;
- `development/schemas/character-asset-manifest.schema.json`: character asset manifest;
- `development/schemas/asset-name-match.schema.json`: asset-name matching output;
- `development/schemas/visual-reference-evidence.schema.json`: visual-reference evidence.

Schemas define exact serialized fields and constraints. This file defines cross-cutting required behavior. Neither plans nor progress files may silently weaken these contracts.

## Document roles

- `docs/specs/`: current durable requirements;
- `development/PLAN.md` and `development/NETEASE_ASSET_PIPELINE_PLAN.md`: implementation/design plans, not requirement authority;
- `development/work/codex-progress.md`: current handoff/progress state;
- `development/evidence/`: evidence and historical investigation records;
- `development/docs/*audit*`: point-in-time audits, retained as history;
- `README.md` and `programs/README.md`: operator/developer documentation derived from the current implementation and specification.
