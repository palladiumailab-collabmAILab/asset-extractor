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

## Character / material join

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

Example:

```powershell
python programs/build_character_asset_manifest.py `
  --characters development/config/character-catalog.tsv `
  --catalog C:\path\to\textured-static-manifest.json `
  --evidence development/config/kainin-asset-variants-20260914.json `
  --output C:\path\to\new-character-join-run
```
