# APK asset corpus classification

This report covers the decoded extraction tree at the time of the v1 batch
run. Source files were read-only throughout.

## Mesh assets

| Category | Count |
|---|---:|
| `.mesh` files | 53,347 |
| Unique mesh payloads (SHA-256) | 21,678 |
| Duplicate mesh files | 31,669 |
| Converted colorized glTF | 21,540 |
| Unsafe or unsupported mesh payloads | 138 |

The 138 mesh failures are classified in
`mesh_conversion_classification_v4extended.md` and
`converted/corpus_all_v4extended_colorized/failures.json`:

- 136 require an additional NeoX layout parser (132 irregular Version 4
  layouts and 4 Version 3 bone-header/name layouts).
- 2 have face indices outside the vertex range and are excluded rather than
  silently clipping topology.

## Texture assets

| Category | Count |
|---|---:|
| Texture files (`.ktx`, `.pvr`, `.dds`, `.astc`, `.png`, `.jpg`, `.tga`, `.bmp`) | 135,222 |
| Unique texture payloads (SHA-256) | 110,586 |
| Converted/reusable outputs | 110,554 |
| Texture failures | 32 |

The texture batch output is under
`converted/textures_all_v1/`. KTX/PVR/DDS payloads that decode successfully
are written as PNG; existing standard images are copied into `native/`.
The 32 failures are recorded in `converted/textures_all_v1/failures.json`:
25 empty-image KTX payloads, 3 non-DX10 DDS payloads, 1 unknown KTX format,
and 3 unsupported PVR pixel formats.

## Metadata and scene assets

The extraction tree also contains 27,365 `.gim`, 27,217 `.mtl`, 4 `.scn`,
1,174 auxiliary `.xml`, and 550 `.atlas` files. GIM/MTL files are metadata,
not standalone renderable geometry; they remain preserved and are referenced
by the mesh and scene manifests. The four scenes remain available for later
placement reconstruction.

## Rebuild commands

```powershell
$py = "C:\Users\palla\Documents\resource\OnmyojiAPK\tools\neoxtractor-venv\Scripts\python.exe"
& $py C:\Users\palla\Documents\resource\OnmyojiAPK\tools\batch_convert_mesh_corpus.py `
  C:\Users\palla\Documents\resource\OnmyojiAPK\extracted `
  --output C:\Users\palla\Documents\resource\OnmyojiAPK\converted\corpus_all_v4extended_colorized `
  --workers 4 --colorize --resume
& $py C:\Users\palla\Documents\resource\OnmyojiAPK\tools\batch_convert_textures.py `
  C:\Users\palla\Documents\resource\OnmyojiAPK\extracted `
  --output C:\Users\palla\Documents\resource\OnmyojiAPK\converted\textures_all_v1 `
  --workers 4 --resume
```

The generated glTF materials use deterministic presentation colors. Original
MTL-to-texture associations are not inferred without an explicit proven path.
