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
python programs/asset_extractor.py extract input/raw/sample.zip --output output/runs/sample --resume
python programs/asset_extractor.py validate-manifest output/runs/sample/run-manifest.json
python -m unittest discover -s development/tests -t .
```

実装計画とSol midのレビュー結果は [development/PLAN.md](development/PLAN.md)、
引き継ぎ状況は `development/work/codex-progress.md` にあります。

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
