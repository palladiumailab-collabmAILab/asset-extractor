# Onmyoji APK Asset Extraction

## Scope

This directory is a non-destructive working copy for converting locally captured
Onmyoji assets into formats that can be inspected in Blender and later imported
into Unreal Engine 5. Original APK, OBB, NPK, texture, and device-copy files are
kept in place; decoded outputs are written under `extracted/` and `converted/`.

## Source

- Package: `com.netease.onmyoji.na`
- Installed version: `1.8.13` / version code `251120`
- Device: Xiaomi 13T Pro, ABI `arm64-v8a`
- APK provenance and hashes: `apk_manifest.json`
- OBB provenance, hashes, and entry lists: `obb_inventory.json`
- Device-copy provenance: `device_data_manifest.json`

The three large root files that were not available through Android shared
storage (`Documents/res.npk`, `tex.npk`, `script.npk`) were not required for
this pass. The APK, both OBBs, `Documents/ExtraRes/res.npk`, and
`Documents/OptionRes/*.npk` provided readable NXPK assets.

## Environment

- Windows PowerShell
- Python 3.13.15: `C:\Users\palla\AppData\Local\Programs\Python\Python313\python.exe`
- Extraction virtual environment: `tools/neoxtractor-venv`
- NeoXtractor source checkout: `tools/NeoXtractor-source-v3.2`
- Portable Blender 5.2.1 LTS: `tools/blender/Blender 5.2.1/`
- Unreal Engine 5.8 is installed separately on this machine; project import is
  still a later phase.
- The existing Astra Blender MCP setup was started on `localhost:9876` and
  successfully returned scene information and a viewport screenshot. Its
  reusable runtime and addon remain under `C:\Users\palla\Documents\astra-blender-lab`.

## Required Software

NeoXtractor v3.2 was downloaded from the official GitHub release and retained
under `tools/`. Its release SHA-256 and source commit are recorded in
`tools/extractor_tool_manifest.json`. The repository has no LICENSE/COPYING/
NOTICE file at the recorded commit and its README limits the tool to
educational purposes, so tool licensing remains **UNKNOWN - requires manual
verification**. The game asset license and redistribution rights are separate
and are not inferred here.

## Stage Analysis

- Source format: NeoX `NXPK` / NeoX 2.0 32-byte index entries
- Onmyoji decode profile: basic XOR key `150`, commonly zlib compressed
- Device-copy NPKs: 60 files, approximately 6.92 GiB
- `OptionRes`: 59 NPKs, 73,836 entries, approximately 4.45 GiB
- `ExtraRes/res.npk`: 173,294 entries, approximately 2.48 GiB
- OBB NPKs: `res1.npk`, `res2.npk`, `tex1.npk` through `tex11.npk`, and
  `script.npk`
- Models: `.mesh`, `.skeleton`, animation and XML metadata
- Textures: `.ktx`, `.astc`, `.pvr`, `.png` and related NeoX texture payloads
- Missing textures: not observed in the NPK decode pass; logical filename
  mapping is hash-based and still needs model-material matching
- Unsupported or deferred: direct FBX export in NeoXtractor is an unimplemented
  stub; game-specific material semantics and scene placement are not fully
  reconstructed yet

## Extraction Results

- `extracted/option_models/`: selected character/model NPKs; 1,791 mesh files
  and 2,180 KTX-family texture files were extracted with zero recorded errors.
- `extracted/obb_assets/`: all 11 texture NPKs and both resource NPKs; 108,689
  decoded files, zero recorded errors.
- `extracted/extrares_assets/`: full `ExtraRes/res.npk`; 37,195 selected
  decoded files, including 25,275 mesh entries, zero recorded errors.
- `extracted/extrares_stage_refs/`: additive stage-reference pass over the
  same `ExtraRes/res.npk`; 91,781 decoded files with zero errors, including
  4 `.scn` scene records, 27,217 `.mtl` material records, and 27,365 `.gim`
  image-map records. The main scene XML is
  `res/Other/119133_ffffffffb0919af3.scn` and contains camera, light,
  bounding-box, model names, transforms, and referenced asset paths.
- `converted/model2_2505_sample/`: three skinned sample meshes converted to
  embedded glTF 2.0. The largest sample is 58,850 vertices, 77,611 faces, and
  471 bones.
- Every extraction directory contains `extraction_manifest.json`; each batch
  contains `run_manifest.json`.

## Blender Conversion

`tools/convert_mesh_to_gltf.py` uses NeoXtractor's `MeshLoader` and glTF
converter. It leaves `.mesh` files untouched and writes embedded `.gltf` files.
`tools/convert_mesh_to_gltf_safe.py` is the Blender-compatible bridge: a few
NeoX meshes contain packed/sentinel joint values outside the declared skeleton,
so this separate output maps those values to the root joint and normalizes zero
weight vertices. The original decoded mesh and the first unmodified glTF sample
remain available for comparison. The safe sample was imported headlessly in
Blender 5.2.1 and saved as `blender/validation/model2_2505_safe.blend`.

## Unreal Import

The first UE verification import is complete. The intended path is:

`NXPK -> decoded .mesh/.ktx -> glTF sample -> Blender material/axis cleanup -> Unreal FBX/glTF import`

Two static samples were converted and imported into the existing UE 5.8.2
project `JadeLanternGarden` under `/Game/Environment/OnmyojiAPK/Validation`.
The generated report is `JadeLanternGarden/Docs/apk_stage_import_report.json`.
The map `/Game/Maps/OnmyojiAPKValidation` contains both meshes, a PlayerStart,
Directional Light, Sky Light, Sky Atmosphere, and Exponential Height Fog. The
map load check is recorded in `JadeLanternGarden/Docs/apk_stage_map_report.json`.
The two meshes are technical validation inputs; scene-path-to-hash mapping and
original materials are still unresolved, so this map is not claimed to be a
full reconstruction of the original game scene.

Do not import the entire `extracted/` tree as one level. Use the manifests to
select the stage and character assets, then build `Content/Environment`,
`Content/Materials`, `Content/Textures`, and `Content/Maps` in the UE project.

## Coordinate Conversion

NeoX/MMD coordinates have not been globally baked into Unreal coordinates yet.
Validate X/Y/Z orientation and centimeters in Blender before exporting. UE5 is
Z-up and uses centimeters (`1 UU = 1 cm`). Preserve the decoded source and use
a separate cleaned/export directory for any axis or scale changes.

## Materials

KTX/ASTC/PVR payloads are preserved in their decoded form. Texture decoding and
hash-to-material association are the next required step. Base Color, alpha,
normal, roughness, metallic, and emissive channels must be validated per
material; do not assume MMD/NeoX toon flags map directly to UE materials.

## Collision, Lighting, and Player Controls

The verification meshes use `CTF_USE_COMPLEX_AS_SIMPLE` collision to prove that
the assets can be walked around. This setting is limited to the small
validation map; production ground, buildings, bridges, stairs, and walls should
receive simplified collision. The map has a PlayerStart, an auto-possessed
Third Person character instance using Yingcao, a map-specific native
`GameModeBase`, plus Directional Light, Sky Light, Sky Atmosphere, and
Exponential Height Fog.

## Known Issues

- Root app-data NPK files were blocked by Android external-storage permissions;
  no protected data was bypassed.
- The low-32-bit `mesh_hash` rule now resolves the captured scene's GIM and
  Mesh records; MTL/texture associations remain unresolved unless an explicit
  path or reference is present.
- The safe glTF bridge is a compatibility fallback; its root remapping is not
  a substitute for recovering the game's exact packed skin binding semantics.
- The extraction pass does not infer the original scene graph or object
  placement.
- The main `.scn` is readable XML and its transforms are retained in the batch
  manifest. Mesh-parser gaps and material linkage still prevent a complete
  original scene rebuild.
- The validation converter keeps the first vertex-sized UV block for meshes
  that expose multiple packed UV blocks; the discarded count is recorded in
  `converted/extrares_static_validation_fixed/conversion_manifest.json`.
- Some texture formats need conversion to PNG/TGA or UE-compatible compressed
  formats before material authoring.
- Source asset licensing, redistribution, and commercial-use terms remain a
  manual verification item even for a personal-use prototype.

### Native texture and colored glTF probe

`tools/build_textured_gltf_sample.py` converts one decoded NeoX `.mesh` through
NeoXtractor's MeshLoader, decodes a KTX/ASTC/PVR texture through
`core.images.convert_image`, and assigns the resulting PNG as a glTF base-color
texture. It never writes to either input. For example:

```powershell
& tools\neoxtractor-venv\Scripts\python.exe tools\build_textured_gltf_sample.py `
  extracted\extrares_stage_refs\res\Mesh\152015_ffffffffe0e09138.mesh `
  extracted\extrares_stage_refs\res\Texture\022827_43c8e588395df7f2.ktx `
  --output converted\native_format_probe --provenance technical-probe
```

The sample imports in Blender 5.2.1 as one textured material, 141 vertices,
144 faces, and one UV layer. Blender also exported the self-contained
`152015_ffffffffe0e09138_textured.glb`. This mesh/texture pairing is explicitly
a format probe: the extracted NPK entries are hash-named and the original MTL
association has not been proven. `tools/find_stage_asset_chain.py` attempts the
GIM/mesh/MTL/texture path-hash chain and exits nonzero when it cannot prove a
match.

The reproducible Blender presentation file is
`blender/validation/native_format_probe_textured.blend`; its quick render is
`blender/validation/native_format_probe_textured_render.png`. The UE proof is
created by `JadeLanternGarden/Tools/Unreal/import_apk_textured_probe.py` and
verified by `verify_apk_textured_probe.py`. It creates a project-owned
`StaticMesh`, `Texture2D`, and material under
`/Game/Environment/OnmyojiAPK/NativeProbe`, then places the mesh in
`/Game/Maps/OnmyojiAPKValidation`.

GIM and MTL payloads are XML metadata and can be parsed directly; they are not
image or mesh containers. NeoXtractor exports bind skeletons embedded in `.mesh`
to glTF, but this source tree contains no converter for standalone `.skeleton`
or `.animconfig` animation tracks. Those extensions were added to the
non-destructive extractor allowlist for future investigation.

## License Notes

| Field | Status |
|---|---|
| Source asset | Onmyoji APK/OBB and device-copied NPK assets |
| Original author | NetEase / game-specific third parties; exact attribution varies |
| Source URL | https://play.google.com/store/apps/details?id=com.netease.onmyoji.na |
| License | UNKNOWN - requires manual verification |
| Redistribution | UNKNOWN - requires manual verification |
| Commercial use | UNKNOWN - requires manual verification |
| Modification | Technical extraction only; confirm terms before sharing |

## Rebuild Instructions

1. Keep the original APK/OBB/device-copy files unchanged.
2. Ensure Python 3.13 and `tools/neoxtractor-venv` are available.
3. Set `PYTHONPATH` to `tools/NeoXtractor-source-v3.2`.
4. Run `tools/run_extraction.ps1` to reproduce the selected model, OBB,
   ExtraRes, and stage-reference extraction batches. It stages the 14 OBB NPKs
   when needed and overwrites decoded files for the selected sources while
   leaving all source archives unchanged.
5. Run `tools/convert_mesh_to_gltf.py` on selected `.mesh` files, then validate
   the glTF in Blender before any Unreal import. The reproducible UE sample
   command uses the two sources recorded in
   `converted/extrares_static_validation_fixed/conversion_manifest.json`.
6. Run `JadeLanternGarden/Tools/Unreal/import_apk_stage_samples.py` through
   `UnrealEditor-Cmd.exe -run=pythonscript -script=...`. Set
   `JLG_APK_STAGE_NEW_MAP=1` to create/update the standalone validation map;
   the script never edits the baseline map unless
   `JLG_APK_STAGE_ALLOW_BASE_MAP=1` is explicitly set.
7. Run `JadeLanternGarden/Tools/Unreal/verify_apk_validation_map.py` with the
   same commandlet to confirm map loading, player start, tagged sample actors,
   and lighting.
8. Run `tools/record_extraction_audit.ps1` after a batch to record source
  hashes, the extractor script hash, and the NeoXtractor source commit in
  `run_audit.json` and each source manifest.
9. Run `JadeLanternGarden/Tools/Unreal/import_apk_textured_probe.py` followed by
   `verify_apk_textured_probe.py` to reproduce the color/material UE proof.

## Verification

The current pass completed NXPK decoding with zero recorded extraction errors,
validated the skinned and static glTF conversions in Blender, imported two
static meshes into UE 5.8.2, created the standalone validation map, and passed
both the headless map check and a game-process load test. The validation map
uses the native `GameModeBase` to avoid inheriting unrelated character assets;
the runtime log shows `OnmyojiAPKValidation` loading and exiting without a
fatal error. The full decoded mesh corpus now contains 53,347 files and
21,678 unique payloads; 21,540 are organized as reusable colorized glTF and
138 are classified as unsafe or unsupported. The texture corpus contains
135,222 files and 110,586 unique payloads; 110,554 are organized as PNG or
native reusable images and 32 are recorded as decoder failures.

The native textured probe also passed Blender material/image/render validation
and UE 5.8.2 asset/map verification. It remains explicitly labelled a format
probe until the original mesh-to-texture association is recovered.

### Deterministic scene batch restoration

The scene-reference batch tool is `tools/batch_restore_assets.py`. It uses the
proven low-32-bit suffix rule `mesh_hash(normalized logical path)` to resolve
each scene `AllFiles/*.gim` record to its decoded `.gim` and to the mesh at the
same logical path with the extension changed to `.mesh`. It preserves every
scene model instance's `FilePathIndex`, name, position, rotation matrix, and
scale in the batch manifest. Meshes are converted to shape-only glTF through
`MeshLoader`; UV and skinning compatibility fixes are recorded per asset.

MTL and texture associations are applied only when an explicit unique path or
reference can be proved. Otherwise the asset is still converted as shape-only
glTF and the reason is written to `unresolved.json`; no guessed original
material is attached. The optional `--colorize` flag adds a deterministic
`NeoXColorizedFallback` presentation material for visual inspection. It is not
claimed to reproduce the game's original texture. If an exact MTL reference is
recovered later, the same tool can decode its KTX/PVR/ASTC/PNG-family payload
to PNG without changing the source.

The complete stage-reference pass for `q_dashezhandou` was run with 95 unique
scene GIM paths. It produced 92 glTF meshes and recorded 95 unresolved records
(three missing GIM/Mesh records and the remaining unresolved material/texture
relationships). The reproducible outputs are under
`converted/batch_restore/q_dashezhandou_all_colorized_v4fixed/`, including `batch_manifest.json`,
`unresolved.json`, `conversion.log`, and the `gltf/` directory. The output
manifest retains all 210 scene model instances and their transforms.

Example commands:

```powershell
$py = "tools\\neoxtractor-venv\\Scripts\\python.exe"
$scene = "extracted\\extrares_stage_refs\\res\\Other\\119133_ffffffffb0919af3.scn"
& $py tools\\batch_restore_assets.py extracted\\extrares_stage_refs `
  --scene $scene --limit 12 `
  --output converted\\batch_restore\\q_dashezhandou_all_colorized_v4fixed --colorize
& $py tools\\batch_restore_assets.py extracted\\extrares_stage_refs `
  --scene $scene --all `
  --output converted\\batch_restore\\q_dashezhandou_all_colorized_v4fixed --colorize
```

The default is a bounded 12-unique-mesh run; `--all` processes every uniquely
resolved scene GIM. Original APK, NPK, decoded source meshes, XML, and texture
payloads remain untouched.

### Version 4 / Bone Type 1 compatibility

The first batch exposed 22 meshes that were rejected by the bundled
NeoXtractor parser. All shared the header `Version=4, BoneType=1`. The parser
had two compatibility defects: its type-size checks subtracted vertex blocks
cumulatively, and its parent-index-width heuristic could select uint8 for a
uint16 layout. `NeoXtractor-source-v3.2/core/mesh_loader/parsers/new_parser.py`
now tests the type-2/type-3 layout from the same base size and scores the
uint8/uint16 parent/name layouts before reading bones. The 22 files now pass
MeshLoader, UV/skinning sanitization, and glTF conversion. The corrected batch
contains 92 glTF outputs from 95 scene assets; the remaining three entries do
not have corresponding GIM/Mesh records in the captured extraction tree. The
glTF exporter also normalizes joint indices against the skin joint palette and
binds invalid indices to the detected root joint, preventing invalid `JOINTS_0`
references in Unreal/Blender imports.

### Full corpus batch conversion

The full-tree mesh converter is `tools/batch_convert_mesh_corpus.py`. It uses
SHA-256 deduplication, a conservative four-process pool, validation of finite
vertex data and face indices, atomic writes, and `--resume`. The complete
output is under `converted/corpus_all_v4extended_colorized/`; its manifest and
failure list retain every duplicate source path.

The texture converter is `tools/batch_convert_textures.py`. It converts
supported KTX/PVR/DDS/ASTC payloads to PNG and copies already-standard images
into a native reusable folder. Its complete output is under
`converted/textures_all_v1/`. The aggregate classification and rebuild commands
are recorded in `reports/asset_corpus_classification_v1.md`.


### Astra shape-only recovery

An opt-in validated geometry-only retry recovered 132 of 138 remaining mesh payloads.
The combined total is 21,672 glTF payloads, with six unsupported legacy files.
See `reports/astra_mesh_recovery_v1.md` for evidence, limitations and rebuild commands,
and `converted/corpus_astra_shape_retry_v1/combined_manifest.json` for all output paths.
The original corpus and source files are preserved. New outputs omit UV and skin data.

### Colored scene assembly

`tools/assemble_scene_blender.py` reconstructs the captured
`q_dashezhandou` scene in Blender from the batch manifest. It imports each
resolved glTF template once, creates linked instances using the recorded
position/rotation/scale, converts the NeoX Y-up coordinates to Blender Z-up,
keeps the deterministic colorized presentation materials, and adds a preview
ground, lighting, and camera. The source APK/NPK/extracted files are read-only.

The generated presentation scene is:

`blender/assembled/q_dashezhandou_stage_colored.blend`

The associated render preview and machine-readable check are:

`blender/assembled/q_dashezhandou_stage_colored_preview.png`

`blender/assembled/q_dashezhandou_stage_colored_report.json`

The current assembly contains 92 resolved mesh templates and 204 placed
instances (661 mesh objects). Three logical GIM assets remain unresolved and
account for six omitted instances; their names are retained in the report.
The colorized materials are deterministic visual fallback materials because
the hash-named source texture-to-MTL relationships are not yet proven. In the
Blender viewport use Material Preview (`Z`, then `M`) to see the colors.

Rebuild it with:

```powershell
$blender = "tools\\blender\\Blender 5.2.1\\blender-5.2.1-windows-x64\\blender.exe"
& $blender --background --python tools\\assemble_scene_blender.py -- `
  converted\\batch_restore\\q_dashezhandou_all_colorized_v4fixed\\batch_manifest.json `
  blender\\assembled\\q_dashezhandou_stage_colored.blend `
  blender\\assembled\\q_dashezhandou_stage_colored_preview.png
```
