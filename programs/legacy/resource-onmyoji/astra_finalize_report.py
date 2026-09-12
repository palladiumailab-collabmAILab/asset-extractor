import json
from pathlib import Path
R=Path(r'C:\Users\palla\Documents\resource\OnmyojiAPK');out=R/'converted/corpus_astra_shape_retry_v1'
b=json.loads((R/'converted/corpus_all_v4extended_colorized/batch_manifest.json').read_text());a=json.loads((out/'batch_manifest.json').read_text());retry={r['sha256']:r for r in a['assets']};probe={r['sha256']:r for r in json.loads((R/'reports/astra_probe.json').read_text())}
rows=[]
for r in b['assets']:
 r=retry.get(r['sha256'],r).copy()
 if r['status']=='failed':
  q=probe[r['sha256']];r['failure_class']='version0_unknown_auxiliary_flag_2' if q.get('args') else 'version3_unsupported_bone_header'
  r['baseline_diagnostic']=q.get('error','face index outside vertex range')
 rows.append(r)
combined={'schema_version':1,'source_policy':'read-only','unique_payloads':len(rows),'baseline_gltf':21540,'additional_shape_only_gltf':132,'available_gltf':sum(r['status']!='failed' for r in rows),'remaining':sum(r['status']=='failed' for r in rows),'source_manifests':[str(R/'converted/corpus_all_v4extended_colorized/batch_manifest.json'),str(out/'batch_manifest.json')],'assets':rows}
assert combined['available_gltf']==21672 and combined['remaining']==6
assert all(Path(r['output']).is_file() for r in rows if r['status']!='failed')
(out/'combined_manifest.json').write_text(json.dumps(combined,indent=2),encoding='utf-8')
(R/'reports/astra_remaining_classification.json').write_text(json.dumps([r for r in rows if r['status']=='failed'],indent=2),encoding='utf-8')
report='''# Astra追加解析・形状限定回収

2026-09-07。元データと既存21,540 glTFは変更していません。

- 対象138 unique payload中132件を追加glTF化。合計21,672 / 21,678、残り6件。
- 新規出力: `converted/corpus_astra_shape_retry_v1/gltf/`。
- 全件の参照先: 同フォルダの `combined_manifest.json`。既存manifestのasset情報を保持し、救済分だけ置き換えています。

## 根拠と制限

132件はVersion 4、骨種別0/1、単一mesh、float32頂点・法線、auxiliary flag 0/1、uint16 face stream。既存parserの全体サイズ判定が未知の後続データのため拒否していました。既知のgeometry blockは全件で整合します。

`new_parser.py`に明示呼び出しの`parse_shape_only`を追加。通常parseの判定は変更していません。頂点/face数の上限、有限値、座標絶対値<1e6、法線の99%以上が二乗長0.8〜1.2、flag、face block終端、全index範囲、非退化faceの存在を検証します。全体サイズ判定を緩めて未知のUVやskinを読ませる方法は採用していません。

出力は静止形状と法線のみを確実に回収し、UVはゼロ、骨・joint・weightを省略。決定的な表示用色は原作materialではありません。省略情報をglTF extrasと各manifest assetへ明記しています。アニメーション/原作テクスチャの復元を意味しません。

## 検証

- 全132件のglTF bufferを再デコードし、POSITION/NORMAL/indexが解析した元blockと完全一致。
- 各変換前後で元mesh SHA-256が失敗一覧と一致。
- Blender 5.2.1で132件すべてimport成功。全頂点数一致。22件で計167の重複/退化三角形がBlenderに除去されますが、全差分が元index列の同一頂点集合の重複/退化と一致。glTF自体は元index列を保持。
- 通常parserを変更前snapshotと33既存サンプルで比較し、serialize結果完全一致。
- 意図的に破損させたNaN法線、範囲外index、未知flag、Version3をすべて拒否。
- 詳細: `reports/astra_parser_validation.json`、`reports/astra_blender_validation.json`、`reports/astra_probe.json`。

## 残る6件

- 4件: Version3の骨header。既存parserが骨名UTF-8 decodeに失敗。骨headerの構造自体が未対応の可能性があり、単なる文字コード置換は行わない。Version4の親index幅変更を強制しても改善しない（Version3にその分岐は適用されない）。
- 2件: Version0、auxiliary flag=2。既存処理では各5個の範囲外indexが発生。face開始を単純に±数byteずらしても正当性が証明できないため未変換。未知flagの意味と末尾制御データの解読が必要。
- SHA-256、元path、既存診断は `reports/astra_remaining_classification.json`。

## 再構築

既存環境を使い依存インストールは不要。以下はOnmyojiAPKルートで実行。

```powershell
& .\\tools\\neoxtractor-venv\\Scripts\\python.exe .\\tools\\retry_mesh_shapes_astra.py
& .\\tools\\neoxtractor-venv\\Scripts\\python.exe .\\tools\\astra_validate_parser.py
& '.\\tools\\blender\\Blender 5.2.1\\blender-5.2.1-windows-x64\\blender.exe' --background --python .\\tools\\astra_blender_validate.py
& .\\tools\\neoxtractor-venv\\Scripts\\python.exe .\\tools\\astra_verify_blender_counts.py
& .\\tools\\neoxtractor-venv\\Scripts\\python.exe .\\tools\\astra_finalize_report.py
```

retryは失敗一覧138件のみを処理し別フォルダへ一時ファイルからatomic置換します。再実行可能で既存corpusは更新しません。元の失敗一覧は履歴として138件を保持し、現在の総数はcombined manifestを参照してください。
'''
(R/'reports/astra_mesh_recovery_v1.md').write_text(report,encoding='utf-8')
print({k:v for k,v in combined.items() if k!='assets'})
if '### Astra shape-only recovery' not in (R/'README.md').read_text():
 with (R/'README.md').open('a',encoding='utf-8') as f:f.write('\n\n### Astra shape-only recovery\n\nAn opt-in validated geometry-only retry recovered 132 of 138 remaining mesh payloads.\nThe combined total is 21,672 glTF payloads, with six unsupported legacy files.\nSee `reports/astra_mesh_recovery_v1.md` for evidence, limitations and rebuild commands,\nand `converted/corpus_astra_shape_retry_v1/combined_manifest.json` for all output paths.\nThe original corpus and source files are preserved. New outputs omit UV and skin data.\n')
