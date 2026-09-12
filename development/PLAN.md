# アセット自動抽出プログラム開発計画

作成日: 2026-09-12
レビュー担当: `gpt-5.6-sol` / reasoning `medium`
レビュータスク: `01a0953c-a0dc-7b42-ac9d-fb64a252c587`

## 1. 目的と対象

許可されたローカルのAPK、分割APK、ZIP形式OBB、既知のNXPK/NPKを、原本を
変更せずに棚卸し・抽出・変換する。入力、使用ツール、設定、出力をハッシュで
結び、中断・再実行・部分失敗を正確に記録する。

対象外は、認証・DRM・アクセス制御・Android権限の回避、秘密情報や資格情報の
抽出、抽出物の実行、根拠のない原作材質・アニメーションの復元、GitHub等への
大容量原本の送信、ライセンスの自動判定である。

## 2. 既存工程の検証結果

### 事実

- `android-apk-analysis` で `pm path` → ADB回収 → APK ZIP展開 → `assets/`複製
  → ファイルSHA-256・カテゴリ集計の汎用入口が作られた。
  `Documents/android-apk-analysis/README-ja.md:27`、
  `tools/pull-installed-apk.ps1:18`、`tools/extract-apk-assets.ps1:46`
- KiwixではAPK 68,754,256 bytes、ZIPエントリ1,136、展開ファイル1,063、
  `assets/` 17ファイルを確認した。実行時に取得したZIMはAPK内資産と分離した。
  `extracted/kiwix-v3.14.1/reports/analysis.json:2`
- OnmyojiではエミュレータのSIGILL・メモリ不足を受けてBlueStacksへ移行し、
  APK/OBB/NPKを回収した。OBBから14本のNPKと16本のMP4を取り出し、NXPKの
  32-byte index、XOR、zlibを扱った。
  `Onmyoji-APK-Assets/reports/progress-log.md:13`、
  `reports/downloaded-assets-notes.md:7`
- 後期の`resource/OnmyojiAPK`では、NeoXtractorを使い、NPK展開、mesh→glTF、
  テクスチャ→PNG、SCN→GIM→meshのハッシュ解決、Blender/UE検証へ発展した。
  `resource/OnmyojiAPK/README.md:210`
- 既存成果には、mesh/textureのSHA-256重複排除、原子的出力、`--resume`、
  失敗一覧がある。Version 4/BoneType 1の互換性問題は修正され、形状限定の
  Astra再試行では元の意味的復元と区別して記録された。
  `tools/batch_convert_mesh_corpus.py:168`、
  `reports/astra_mesh_recovery_v1.md:3`

### 強い推論

- `android-apk-analysis` は汎用的な回収・棚卸し入口、`Onmyoji-APK-Assets` は
  ゲーム固有形式の試作・成果、`resource/OnmyojiAPK` は再現性を高めた統合工程
  と位置づけられる。
- 後期Python実装の価値は、初期PowerShellの単純な展開よりも、重複排除、失敗
  保持、原子的書き込み、推測しない関連付けにある。

### 未確定・既知の弱点

- split APKのbase判定が列挙順に依存する。
- ZIP展開は古い出力を残し得る。NXPKの欠落入力がskip扱いになる場合がある。
- `--resume` が非ゼロサイズだけを信用し、source/tool/configの整合を再検証しない。
- OBB stagingと処理対象の差、旧状態と現状態が同一manifestに混在する。
- 材質・テクスチャ対応、スキニング、アニメーション、論理パスの一部は未解決。
- 解凍爆弾、総出力、圧縮率、パストラバーサル、シンボリックリンクの統一防御が
  不十分。cloudfilesys復号は既定自動処理へ入れず、明示プロファイルに隔離する。

## 3. 4領域の構成

```text
input/
  raw/          原本。プログラムはread-only
  manifests/    由来、package/version、サイズ、SHA-256、取得状態
  profiles/     明示承認済みの形式プロファイル
output/
  runs/<run-id>/staged|extracted|converted|reports|logs/
  legacy/       既存成果の分類保存（Git対象外）
  work/         中間・作業用成果（Git対象外）
programs/
  src/asset_extractor/  保守対象MVP
  vendor/               外部ツールの参照・manifest（原則Git対象外）
development/
  tests/                unittestの単体・統合テスト
  fixtures/             合成fixtureと小規模golden
  schemas/              manifest schema
  evidence/             過程・試行錯誤・既存レポート
  docs/                 運用・安全境界
  work/                 Codex進捗と採点記録
```

各runは新規ディレクトリに書き、完了時だけ`complete`にする。`input/raw`への
書き込み、入力との同一・包含出力、ハードリンク、in-place renameは禁止する。

## 4. 段階的な実装計画

1. **Phase 0: 契約・安全境界**
   CLI、manifest、終了コード、`fact/strong_inference/unknown`、パス境界、
   エントリ数・単体サイズ・総出力・圧縮率上限を固定する。
2. **Phase 1: inventory-only MVP**
   APK/OBB/NPKのmagic、サイズ、SHA-256、ZIPエントリを`scan`で列挙する。
   既定導入はdry-runとし、Kiwix値と合成ZIPを回帰対象にする。
3. **Phase 2: 安全なAPK/OBB展開**
   ZIP Slip、絶対パス、予約名、重複・大小文字衝突、symlinkを拒否し、run単位
   の一時出力とatomic manifestを使う。split APKはsource setとして扱う。
4. **Phase 3: NXPKアダプタ**
   既存`extract_nxpk.py`を形式アダプタとして包み、欠落入力、bounds、圧縮方式、
   展開後サイズ、暗号化/error flagをfail-closedで扱う。cloudfilesys復号は
   自動選択しない。
5. **Phase 4: 変換プラグイン**
   texture/mesh/audioを分離し、resume keyをsource hash + converter hash/version
   + normalized configとする。shape-only等の修復種別をmanifestへ記録する。
6. **Phase 5: scene関連付け**
   証明済みlow-32-bit hash規則をプロファイル化し、MTL/textureは一意な明示参照
   のみ採用する。`strict`と`best-effort`を分ける。
7. **Phase 6: 大規模運用**
   4 worker以下、空き容量preflight、JSONL進捗、resume/中断検証を整え、smoke
   →100 unique→全量の順に昇格する。

今回の実装では、Phase 0〜2と、NXPKの最小fail-closedアダプタ（Phase 3の入口）を
完成させる。大規模NPKの形式差分、変換、scene関連付けは安全な拡張点として残す。

## 5. 採点基準

| 項目 | 点 |
|---|---:|
| 原本不変・権限境界・パス安全性 | 20 |
| 抽出正確性・形式検証・fail-closed | 20 |
| 再実行性・atomicity・中断再開 | 15 |
| provenance・manifest・hash連鎖 | 15 |
| 自動テスト・fixture・回帰検証 | 15 |
| ログ・終了コード・partial failure | 10 |
| 保守性・依存固定・ライセンス記録 | 5 |
| **合計** | **100** |

90点未満なら、Solが不足項目と修正案を記録し、Luna max相当の実装者が
修正して再検証する。必須ゲートは、入力前後SHA-256一致、出力外書き込みゼロ、
traversal/未対応/欠落の黙示成功禁止、manifestと実体の相互検証、外部通信なし。

## 6. 受け入れ条件

- `scan`が入力を変更せず、種類・サイズ・SHA-256・検出根拠を出力する。
- 欠落入力は展開前に非ゼロ終了し、manifestへ記録する。
- 入力配下・入力と同一・入力を包含する出力先を拒否する。
- 正常fixtureを2回実行し、時刻以外のmanifestと出力hashが一致する。
- 出力を1 byte改変したresumeが検出・再生成する。
- ZIP Slip、absolute path、異常圧縮率、上限超過を出力外書き込みなしで拒否する。
- manifestが入力・選択エントリ・結果・source/output hash・tool/config hashを持つ。
- `strict`と`best-effort`の状態・終了コードを区別する。
- 実データはCIへ複製せず、既知ハッシュと小規模許可fixtureで回帰する。
- ハーネスの検証、unittest、manifest再計算をローカル一括コマンドで実行できる。
