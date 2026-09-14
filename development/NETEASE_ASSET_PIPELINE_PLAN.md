# NetEase / NeoX asset pipeline improvement plan

Created: 2026-09-14

## Outcome

Turn the current collection of safe extraction and analysis scripts into one
auditable pipeline:

```text
canonical source
  <- read-only BlueStacks ADB acquisition + snapshot manifest
  -> dedicated OSS differential gate
  -> immutable raw extraction + normalized entry provenance
  -> type classification
  -> mesh/material/Tex0 texture resolution
  -> technical 3D+texture candidate
  -> SHA-256-pinned reference-image comparison
  -> verified semantic publication or explicit unresolved result
```

A converted glTF is a technical result. It is not a confirmed character or
costume until a visual reference gate passes. Candidates remain available for
review, but only verified results enter the semantic publication set.

## Issue mapping

| GitHub issue | Pipeline responsibility | Current starting point |
|---|---|---|
| #1 game dictionary matching | Join logical path tokens to external, replaceable game dictionaries | `build_character_asset_manifest.py` supports the Onmyoji four-column table |
| #2 dedicated NeoX extractors | Execute pinned NeoXtractor and neox_tools implementations and compare them with the maintained parser | `run_pilot.py` has executed a three-way canonical pilot |
| #3 entry provenance | Keep logical path, archive/entry identity, hashes, offsets and derived-output lineage | Raw and converted manifests contain parts of the chain but no single normalized contract |

## Non-negotiable gates

1. Canonical APK/OBB/NPK inputs are read-only and have matching pre/post hashes.
   BlueStacks acquisition uses a new local snapshot, compares remote size/mtime
   before and after transfer, and hashes every copied file.
2. An Onmyoji/NeoX variant is promoted only after at least two independent
   implementations agree on entry boundaries, flags, sizes and payload hashes.
3. Raw payloads are immutable. Conversion writes to a new run and records
   source, tool, configuration and output hashes.
4. Mesh/material/texture binding must come from explicit NeoX references and
   deterministic hash resolution. Color, filename proximity and visual
   similarity cannot invent a material binding.
5. Character/costume publication requires both a technically verified
   textured model and at least one SHA-256-pinned image reference attached to
   the exact logical-path decision.
6. Missing, ambiguous and conflicting evidence remains unresolved. It is never
   converted into a successful claim by a fallback heuristic.

## Delivery phases

### Phase A: visual evidence publication gate

- Define a portable evidence-map schema with stable reference IDs.
- Require SHA-256 for image evidence and verify local files when supplied.
- Separate `selection_status` from `publication_status`.
- Publish only when the model output hash, material/texture join and exact
  visual evidence all pass.
- Keep every blocked candidate and a machine-readable reason.

### Phase B: normalized backend interface

- Extract NeoXtractor and neox_tools invocation/provenance code from
  `run_pilot.py` into maintained backend adapters.
- Support `auto`, explicit backend and `differential` modes.
- Prefer a dedicated NetEase/NeoX backend only when its pinned tool and game
  profile are available; otherwise fail explicitly or use a user-selected
  generic fallback.
- Normalize backend output without trusting only its exit code.

### Phase C: entry and derived-asset provenance

- Introduce a stable asset ID derived from source SHA-256 plus entry identity.
- Preserve entry index, index-record offset, payload offset, sizes, flags,
  logical path state and payload SHA-256 for all asset classes.
- Link KTX/PVR/TGA -> PNG and mesh -> glTF outputs through parent asset IDs and
  converter/version/configuration hashes.
- Extend resume validation to reject provenance drift.

### Phase D: generic dictionary and matching package

- Move table parsing, normalization and exact/alias matching into the maintained
  package rather than an Onmyoji-only script.
- Keep dictionaries and prefix/suffix rules external and versioned.
- Reuse the matcher for texture, illustration, animation, audio and effect
  assets when source provenance supports the association.

### Phase E: review UI and reproducible visual comparison

- Present reference image, rendered candidate and technical evidence together.
- Record reference/render hashes, crop/view settings, reviewer decision and
  unresolved reason.
- Clearly separate technical candidates from verified semantic assets in the
  viewer and exported manifest.

### Phase F: migration and release

- Migrate existing Onmyoji pilot/staged/textured/character evidence manifests.
- Add synthetic malformed fixtures and a small licensed golden fixture.
- Run unit tests, schema validation, deterministic repeat runs and source
  pre/post verification.
- Document the supported NeoX variants and intentionally unsupported cases.

## Initial implementation slice

Phase A starts first because it prevents a technically valid but semantically
wrong 3D+texture result from being presented as confirmed. The initial slice
adds the visual evidence schema, SHA-256-pinned reference validation,
publication status, and regression tests.

The Phase C foundation is also implemented for new raw extraction manifests:
stable `asset_id`, source index/hash, backend, logical-path state, asset type,
and reserved `parent_asset_id`. Old version-2 entry records remain valid so
existing evidence can be migrated rather than discarded. Derived-output
lineage and converter provenance remain part of the next Phase C slice.

Phase B backend adapters are the next implementation priority. They build on
these gates without weakening the existing extraction safety contract.

## Acceptance criteria

- A verified variant cannot be generated without high-confidence image
  evidence containing a valid SHA-256.
- If an evidence file path is supplied, its current bytes must match the
  declared hash.
- A verified visual decision with a missing/invalid model output or unresolved
  texture join remains blocked.
- Unmapped family variants remain candidates and are never silently selected.
- Evidence maps contain no required machine-specific absolute path; private
  attachments may be identified by stable source references and hashes.
- The existing safe extraction tests continue to pass.
- Later backend and provenance phases preserve compatibility with the current
  canonical Onmyoji run evidence and do not require committing raw assets.
