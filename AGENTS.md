# Asset extraction automation

This repository follows the Codex development harness. Keep changes small and
reviewable, preserve existing user changes, and run the proportionate checks
before committing.

The project is limited to authorized local APK/OBB/NPK compatibility analysis.
Do not bypass authentication, DRM, access controls, or licensing restrictions;
do not execute extracted payloads; and never commit credentials or large raw
asset corpora.

Repository layout:

- `input/` contains read-only source files and provenance manifests.
- `output/` contains generated runs, validation results, and legacy outputs.
- `programs/` contains the maintained implementation and vendor references.
- `development/` contains plans, evidence, fixtures, schemas, and tests.

Every extraction run must write to a new output directory, record source/tool/
configuration hashes, and make partial or unresolved results explicit.
