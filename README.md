# Asset extraction automation base

許可されたローカルAPK/OBB/NPK等を、原本不変・監査可能・再実行可能な形で
棚卸しし、段階的に抽出・変換するためのベースリポジトリです。

## 4領域

```text
input/        原本（読み取り専用）、入力由来、形式プロファイル
output/       run単位の生成物、旧成果物、作業中間物
programs/     保守対象プログラム、外部ツールの参照情報
development/  計画、証拠、fixture、schema、テスト、進捗
```

`input/raw` と `output` の大容量ファイルはローカルで保持しますが、APK・
OBB・ゲーム資産・生成バイナリは容量と権利上の理由でGitHubへ送信しません。
代わりに `input/manifests` と `development/evidence` にハッシュ、由来、
件数、再現手順を記録します。

整備済みCodexハーネスは `.githooks/`、`.github/`、`scripts/`、`skills/` として
導入済みです。ローカル検証は `pwsh scripts/validate-harness.ps1 -SkipDocker` で
実行できます。PythonがPATHにない場合は、既存環境のPython実行ファイルを指定して
`python -m unittest discover -s development/tests -t .` を実行してください。

## 使い方

```powershell
python programs/asset_extractor.py scan input/raw/sample.zip --report output/runs/scan/run-manifest.json
python programs/asset_extractor.py extract input/raw/sample.zip --output output/runs/sample
python programs/asset_extractor.py extract input/raw/res.npk --output output/runs/onmyoji --backend auto --game-profile onmyoji
python programs/asset_extractor.py extract input/raw/sample.zip --output output/runs/sample --resume
python programs/asset_extractor.py validate-manifest output/runs/sample/run-manifest.json
python programs/asset_extractor.py match-assets --dictionary game.csv --assets assets.json --output matches.json
python programs/run_minimal_restore_test.py `
  --source C:\Users\palla\Documents\ChatGPT\Onmyoji-Canonical-Source\obb\patch.251120.com.netease.onmyoji.na.obb `
  --output C:\Users\palla\Documents\ChatGPT\Onmyoji-Extraction-Workspace\runs\minimal-restore-test-20260915
python programs/asset_extractor.py pipeline `
  --config development/config/pipeline.example.json `
  --output C:\Users\palla\Documents\ChatGPT\Onmyoji-Extraction-Workspace\runs\pipeline-20260915
python -m unittest discover -s development/tests -t .
```

最小復元テストは、OBB/ZIPから動画1件と画像1件だけをPythonの`zipfile`で抽出し、
拡張子ではなくmagic bytesで形式を判定します。各ファイルは読み取り中のSHA-256、
CRC-32、復元先を再読取したSHA-256とサイズを照合し、入力原本も処理前後に再ハッシュ
します。外部extractor、シェル、ビューア、デコーダ、抽出payloadの実行はありません。
出力先は毎回新規でなければならず、`minimal-restore-manifest.json`に全判定を記録します。
OBB直下に画像がない場合は、内包されるNXPKを小さい順にPythonで検証し、最初の
画像payloadだけを復元します。調査用NXPKの一時コピーはrun完了前に除去されます。
終了コードは`0=complete`、`1=partial`、`2=failed`です。複数のOBBを渡す場合は
`--source`を繰り返し、期待する原本ハッシュは同じ順番で
`--expected-source-sha256`を繰り返します。

BlueStacksのADBで通常に読み取れるOnmyoji `OptionRes`を、新しいsnapshotへ
取得する場合は次を使用します。転送前後のremote metadataと全local SHA-256は
`snapshot-manifest.json`へ記録されます。

```powershell
python programs/pull_bluestacks_snapshot.py `
  --adb C:\Android\platform-tools\adb.exe `
  --serial 127.0.0.1:5555 `
  --output C:\Onmyoji-Snapshots\device-assets-new `
  --include-installed-apks
```

既存出力の再利用、root、`run-as`、アクセス制御の回避は行いません。詳しい指定は
[programs/README.md](programs/README.md)を参照してください。

実装計画とSol midのレビュー結果は [development/PLAN.md](development/PLAN.md)、
引き継ぎ状況は `development/work/codex-progress.md` にあります。
NetEase / NeoX OSS、3D＋テクスチャ、参照画像照合を一体化する改良計画は
`development/NETEASE_ASSET_PIPELINE_PLAN.md` にあります。

NeoXのKTX/ASTC等をPNGへ変換する実行環境が通常のPythonと異なる場合は、
`prepare_textured_pilot.py --runtime-python <python.exe>`を使用します。出力作成前に
必要モジュールを検査し、実際のPython・依存versionをmanifestへ記録します。
テクスチャ公開のstatusは実際のモデル変換結果から算出され、全件成功は`complete`、
一部成功は`partial`、成功0件は`failed`となり、終了コードも同じ契約に従います。

## 安全境界

- 入力原本は変更しない。抽出物は必ず新しいrunディレクトリへ書く。
- ZIPの絶対パス、`..`、重複・大小文字衝突、シンボリックリンクを拒否する。
- エントリ数、単体サイズ、総出力サイズ、圧縮率を上限で制限する。
- 抽出物を実行しない。認証・DRM・アクセス制御の回避はしない。
- 不明形式、欠落入力、部分成功はmanifestと終了コードで明示する。
  終了コードは`0=complete`、`1=partial`、`2=failed`で、best-effortの部分成功と
  失敗を区別する。

## Run manifest and resume contract

- `extract`は最終runを同一親ディレクトリ内の一時runからatomicに確定する。
  失敗時に既存の出力runを削除せず、`--report`を指定すれば失敗manifestも指定先へ
  atomicに保存する。
- 各入力には`source_sha256_before`、`source_sha256_after`、
  `source_unchanged`を記録する。抽出完了直前の再ハッシュが一致しないrunは
  `complete`/`partial`にせず`failed`とする。
- `--resume`は単なるファイル存在確認を行わない。入力SHA-256、tool名・version、
  正規化設定から作った`resume_key`とmanifestを照合し、出力全ファイルのサイズ・
  SHA-256・symlink不在を再検証する。不一致や改変は明示的に拒否し、既存runを
  自動削除しない。
- `development/schemas/run-manifest.schema.json`が成功・部分成功・失敗を含む
  manifestの厳格な契約であり、`validate-manifest`で標準ライブラリだけの検査を
  一括実行できる。
- NXPKはentry数・各entryのarchive bounds・実読取長・圧縮後サイズ・総展開量・未知
  flagを検証する。未知の圧縮方式やflagはfail-closedで拒否する。
- 新しい抽出entryは、source SHA-256とentry identityから作る安定`asset_id`、
  backend、asset type、論理パスの有無と理由を保持する。ZIP member pathは既知の
  論理パスとして記録し、名前を持たないNXPK indexは`null`と未取得理由を記録する。
  `parent_asset_id`は後続のPNG/glTF等をraw entryへ結ぶために予約する。

## Unified pipeline

`pipeline`は、設定JSONを一つ渡すだけで、入力取得または指定済み原本の選択、
抽出、共通形式判定、同名3D/画像ペアの作成、NeoXテクスチャ公開、レンダー、
参照画像の候補スコアリングを順番に実行します。各段階は同じrunディレクトリへ
manifestを残し、未設定・未解決・曖昧な結果は`partial`または`failed`になります。

BlueStacksを使う場合は`source`の代わりに`acquisition`を設定します。これは
PythonからADB実行ファイルを呼び出すため、ADB接続・読み取り可能なパス・
NeoXtractorのcheckoutとその依存環境は別途必要です。専用backendを複数入力へ適用
した場合は、各backend実行を保持した`backend-runs-manifest.json`を生成し、汎用
`run-manifest.json`とは別の契約として扱います。参照画像の比較は候補順位を作るだけ
で、十分な特徴点インライアとスコア差がない候補は採用せず、画像からUVやTex0を推測
して書き換えません。

設定例は[development/config/pipeline.example.json](development/config/pipeline.example.json)、
スキーマは[development/schemas/pipeline-config.schema.json](development/schemas/pipeline-config.schema.json)
を参照してください。OpenCVによる参照画像スコアと、定評ある3Dレンダーを使う場合は
`requirements-vision.txt`を使用します。
