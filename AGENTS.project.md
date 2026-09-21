# Project-specific Codex instructions

## Project purpose
- Maintain authorized local APK/OBB/NPK compatibility analysis and asset-restoration workflows with explicit provenance.

## Safety / provenance invariants
- Do not bypass authentication, DRM, access controls, licensing restrictions, root protections, or application sandboxes.
- Do not execute extracted payloads.
- Treat `input/` as read-only source/provenance data; never modify source artifacts in place.
- Write each extraction to a new output location and keep source/tool/configuration identity and hashes sufficient for audit/reproduction.
- Preserve the run status contract `complete` / `partial` / `failed`; unresolved required evaluation cannot be reported as complete.
- Never transmit large proprietary asset corpora or credentials.

## Repository layout
- `input/`: source files and provenance.
- `output/`: generated runs and validation results.
- `programs/`: maintained implementation/vendor references.
- `development/`: plans, evidence, fixtures, schemas, tests, handoffs.
- `docs/specs/`: durable requirements.

## Verification
- Use the repository's canonical extractor tests, schema/domain validation, and configured CI relevant to the change.
