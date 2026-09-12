# 既存作業記録の整理

既存の3系統を読み取り専用で確認し、次の分類へ移した。`history/` はGitへ
記録する要点、`raw/` は大容量・生成物を含む現物の保存場所でありGit対象外。

| 旧系統 | input | output | programs | evidence |
|---|---|---|---|---|
| `Documents/android-apk-analysis` | APK、ダウンロード原本、SDK補助 | Kiwix展開、runtime、画面・emulatorログ | APK回収・展開PowerShell | README、レポート |
| `Documents/Onmyoji-APK-Assets` | APK、downloaded OBB/NPK等 | APK/NPK/WPK/THFB展開、converted、gallery、work | NXPK/WPK/THFB/cloudfilesys試作 | README、progress、completion、notes、reports |
| `Documents/resource/OnmyojiAPK` | APK、OBB、ADB device copy、provenance JSON | extracted、converted、Blender、staging、work | NXPK・mesh・texture・scene・auditツール | README、分類・復旧・最終検証レポート |

## 保存方針

- `input/raw` は原本を変更せず保存する。入力ハッシュは `input/manifests` に置く。
- `output/legacy` は過去の抽出・変換結果を run と混同しないために隔離する。
- `programs/legacy` は自作・作業用スクリプト、`programs/vendor` はNeoXtractor、
  Blender、SDK、仮想環境等の外部ツールを保存する。
- 全量レポートは`development/evidence/raw`へ移し、重要な小規模資料だけを
  `development/evidence/history`へ複製してレビュー可能にする。
- `input/raw`、`output`、vendor、raw evidenceは容量・権利上GitHubへ送らない。
