# Programs

`src/asset_extractor/` is the maintained, standard-library MVP. `legacy/` holds
the historical scripts that explain the extraction path. `vendor/` contains
external tools, SDKs, portable binaries, and virtual environments; their
versions and licensing state are recorded in the historical manifests and are
not committed as binaries.

## BlueStacks raw acquisition

`pull_bluestacks_snapshot.py` captures ADB-readable raw files into a new local
snapshot and writes `snapshot-manifest.json`. It inventories every configured
remote root before and after transfer, pulls files individually, records local
SHA-256 values, and marks the run incomplete if remote size/mtime changes.
It never requests root or `run-as` and refuses to reuse an output directory.
Default safety limits are 50,000 files, 16 GiB per file, and 64 GiB total;
the three `--max-*` options can lower or explicitly raise these limits.

The default remote root is Onmyoji's `Documents/OptionRes`. Installed base and
split APKs can be included through `--include-installed-apks`. Additional roots
must be explicit and can use `{package}` in the remote path.

```powershell
python programs/pull_bluestacks_snapshot.py `
  --adb "C:\Android\platform-tools\adb.exe" `
  --serial 127.0.0.1:5555 `
  --output "C:\Onmyoji-Snapshots\device-assets-20260914-230000" `
  --include-installed-apks
```

Example with an additional authorized source root:

```powershell
python programs/pull_bluestacks_snapshot.py `
  --output "C:\Onmyoji-Snapshots\device-assets-new" `
  --remote-root "optionres=/sdcard/Android/data/{package}/files/netease/onmyoji/Documents/OptionRes" `
  --remote-root "documents=/sdcard/Android/data/{package}/files/netease/onmyoji/Documents"
```

Do not select app-private paths that require root, `run-as`, authentication
bypass, or permission changes. Snapshot manifests follow
`development/schemas/bluestacks-snapshot.schema.json`.

## Python-only minimal restore test

`run_minimal_restore_test.py` is the smallest end-to-end check for a
BlueStacks-extracted OBB/ZIP. It selects one video and one image, streams each
member with Python's standard-library `zipfile`, detects the container from
magic bytes, and verifies the restored file's SHA-256, byte count, and CRC-32.
It also hashes every source archive before and after the run. The script does
not call an external extractor, shell, viewer, decoder, or extracted payload.
If no image exists directly in the OBB, it checks nested NXPK members in
ascending size order with the maintained Python parser and restores only the
first magic-identified image payload. Temporary NXPK staging files are removed
before the manifest is finalized.

Every run directory must be new. A successful run writes
`minimal-restore-manifest.json`, whose contract is
`development/schemas/minimal-restore-test.schema.json`.

```powershell
python programs/run_minimal_restore_test.py `
  --source "C:\Onmyoji-Canonical-Source\obb\patch.251120.com.netease.onmyoji.na.obb" `
  --output "C:\Onmyoji-Extraction-Workspace\runs\minimal-restore-test-20260915"
```

Use `--video-member` or `--image-member` to pin an exact archive member.
When more than one source archive is supplied, repeat `--source` and provide
one matching `--expected-source-sha256` per source if provenance pinning is
required. Exit status is `0=complete`, `1=partial`, `2=failed`; a failed or
partial run is retained with its manifest for investigation.

## Logical-name matching

`asset-extractor match-assets` joins every asset type to a replaceable CSV or
JSON game dictionary. The first rule is the common game convention that a 3D
character and its illustration/texture share the same logical name. Exact
names, normalized variant names such as `s2_hairen`, and explicit aliases are
evaluated in that order. A model and image resolved to the same dictionary
entity are marked `paired-3d-image`; unmatched and ambiguous rows are retained.

```powershell
python programs/asset_extractor.py match-assets `
  --dictionary development/config/examples/onmyoji-characters.example.csv `
  --assets C:\path\to\backend-run-manifest.json `
  --output C:\path\to\asset-name-matches.json
```

The matcher contains no Onmyoji names. Dictionaries carry game-specific names,
aliases, readings, rarity and arbitrary extra metadata.

## Dedicated NetEase backends

`run_netease_backend.py` wraps user-provided or ignored local checkouts of
NeoXtractor and neox_tools. It supports `--backend auto`, `builtin`,
`neoxtractor`, and `neox-tools`. Auto mode selects a dedicated checkout only
when the input is NXPK/EXPK, a non-generic game profile is supplied, and an
available checkout is found; otherwise it records a builtin fallback reason.

```powershell
python programs/run_netease_backend.py C:\source\model2_1.npk `
  --output C:\runs\model2_1-backend `
  --backend auto `
  --game-profile onmyoji `
  --neoxtractor-root C:\tools\NeoXtractor `
  --neoxtractor-config C:\tools\NeoXtractor\configs\omy_omrc.json `
  --backend-python C:\tools\neoxtractor-venv\Scripts\python.exe
```

The wrapper records checkout commit/tree/dirty state, configuration hash,
source pre/post hash, entry metadata, logical-path availability, output hashes,
selection reason and failures. Upstream code is not redistributed because its
license must be established independently. neox_tools can be selected with
`--neox-tools-root`; it receives a copied input because its published function
writes beside that input.

The selected checkout, configuration, and NPK index are validated before the
requested output directory is created. Dedicated extraction runs use a
temporary sibling directory and commit it with an atomic rename, so a
preflight or backend failure cannot leave a misleading empty run that blocks a
retry.

The maintained CLI exposes the same backend selection through
`asset_extractor.py extract --backend auto|builtin|neoxtractor|neox-tools`.
`builtin` remains the default for backward compatibility; `auto` delegates a
single NPK/EXPK input to the isolated NetEase wrapper when its profile and
checkout satisfy the selection policy.

## Character / material join

`prepare_textured_pilot.py` accepts `--runtime-python` when the launcher
environment does not contain NeoXtractor's binary texture decoders. The script
re-executes itself with that Python executable before creating the output run,
checks the base `Pillow` and `numpy` dependencies, and records the resolved
runtime, versions, and preflight result in both resolver and publication
manifests. The upstream `texture2ddecoder` is loaded lazily only for compressed
textures such as KTX, DDS, PVR, or ASTC; ordinary PNG/JPEG/TGA publication does
not require it. The delegated process still runs this maintained Python script;
no shell conversion step is introduced.

```powershell
python programs/prepare_textured_pilot.py `
  --run-root C:\path\to\verified-extraction-run `
  --output C:\path\to\new-textured-run `
  --source-tree C:\path\to\NeoXtractor `
  --runtime-python C:\path\to\neoxtractor-venv\Scripts\python.exe `
  --only-mesh-sha256 <mesh-sha256>
```

`build_character_asset_manifest.py` is the semantic publication step after
`prepare_textured_pilot.py`. It accepts either the maintained six-column
character table or the four-column table used for the Onmyoji catalog
(`rarity`, `japanese`, `chinese`, `pinyin`). The pinyin key labels logical mesh
path candidates; it does not override the resolver's ordered
`Material_N -> Tex0 -> texture` binding. Exact visual evidence can be supplied
with `--evidence`; all other family variants remain explicit candidates.

`verified` is a publication status, not just a filename match. It requires a
technically complete model/material/texture join, a verified converted-output
hash, and high-confidence evidence tied to at least one SHA-256-pinned image
reference. Evidence maps follow
`development/schemas/visual-reference-evidence.schema.json`. A local image path
is optional for portable manifests, but when present its current bytes must
match the declared hash. Web pages and documents may support a decision, but do
not replace the required image evidence.

The textured publication status is derived from the per-model outcomes: all
selected models must be converted for `complete`, a mixture is `partial`, and
zero converted models is `failed`. The process exit code follows the same
three-state contract.

Example:

```powershell
python programs/build_character_asset_manifest.py `
  --characters development/config/character-catalog.tsv `
  --catalog C:\path\to\textured-static-manifest.json `
  --evidence development/config/kainin-asset-variants-20260914.json `
  --output C:\path\to\new-character-join-run
```

`render_gltf_snapshot.py` renders a self-contained textured glTF with
`trimesh` and `pyrender` through an offscreen OpenGL context. Use `--title` for
the evidence label; the renderer derives its default from the current glTF and
never carries a character name over from another run. Existing PNG and JSON
outputs are not overwritten. Install `requirements-vision.txt` for this
optional rendering stage.
