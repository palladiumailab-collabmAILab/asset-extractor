# Codex progress

## 2026-09-12

- 既存の`android-apk-analysis`、`Onmyoji-APK-Assets`、`resource/OnmyojiAPK`の
  原本・旧成果・スクリプト・記録を`input/`、`output/`、`programs/`、
  `development/`へ分類移動した。原本はGit対象外で、既存元ディレクトリには
  データを残していない。
- Sol mid（task `01a0953c-a0dc-7b42-ac9d-fb64a252c587`）が、過去工程を
  APK/OBB/NPK/NXPK/変換/Blender検証の段階として整理し、100点基準とPhase 0〜6
  の計画を提示した。計画全文は`development/PLAN.md`。
- 整備済みCodexハーネスを導入し、標準ライブラリMVP、JSON manifest、atomic run、
  ZIP安全検査、NXPK最小アダプタ、合成fixtureテストを実装した。
- 実データ検証では、Kiwix APKとOnmyoji APKに同名ZIPエントリが存在するため、
  新実装が安全側で明示的に拒否した。旧レポートの件数と矛盾しないが、上書き規則を
  推測して通す処理は追加していない。小規模`sample.npk`も未知のNXPK圧縮flagを
  fail-closedで拒否した。

## Goal

4領域に整理した、原本不変・監査可能なアセット自動抽出プログラムのMVPを完成させる。

## Current state

- Branch or revision: `codex/asset-extraction-automation` (初回コミット前)
- Working tree status: Sol 76/100指摘の修正実装済み、初回コミット前
- Current implementation boundary: Phase 0〜2とNXPK入口。scan、ZIP/APK/OBB、既知NXPK、
  atomic run、厳格manifest、hash付きresume。

## Completed

- Codex作業記録、既存3系統のREADME・スクリプト・レポートを確認。
- Sol midが既存工程を読み取り専用検証し、計画と採点基準を提示。
- `input/`, `output/`, `programs/`, `development/` の4領域を作成。
- manifest、パス境界、ZIP検査、atomic JSON、合成fixtureの骨格を実装。
- 入力前後hash、NXPKの総容量・bounds・実読取長・展開後サイズ・flag検証、resume、
  manifest検証コマンド、best-effort partial、失敗reportを実装。

## Next smallest task

- 大規模運用・split APK判定・形式差分・変換工程は、今回のMVP外の拡張として別計画で扱う。

## Verification

| Command | Result | Notes |
|---|---|---|
| bundled Python `-m unittest discover -s development/tests -t .` | passed | 25 tests, 1 symlink test skipped |
| bundled Python `-m py_compile ...` | passed | maintained Python files |
| `scripts/validate-harness.ps1 -SkipDocker` | passed | hook, skill, unittest checks |

## Decisions

- 大容量・権利不明のAPK/OBB/NPK/生成資産はGitHubへコミットしない。
- 出力は新規runへ書き、推測による材質関連付けをしない。
- cloudfilesysの復号やゲーム固有の意味的復元は既定MVPへ入れず、明示プロファイルへ隔離する。

## Risks and unknowns

- GitHub remote、owner、公開範囲は未指定で、ローカルremoteは未設定。
- 既存大容量フォルダの物理移動にはワークスペース外への書き込み権限が必要。
- NeoXtractorのライセンスとOnmyoji資産の再配布条件は未確認。

## Sol mid実装後レビュー（76/100）への修正記録

レビューで示された不足点は、入力前後ハッシュ、NXPK上限・境界検証、resumeの
整合性、atomic run確定、manifest契約、回帰テスト、進捗記録の7領域だった。
2026-09-12の修正では次を実装した。

1. 成功・部分成功・失敗のextract/scan manifestで、各入力に
   `source_sha256_before`、`source_sha256_after`、`source_unchanged`を記録する。
   抽出完了直前に全入力を再ハッシュし、既知入力の不一致・再ハッシュ不能は
   `failed`としてcommitしない。欠落入力はhashを`null`、安定性を`unknown`として
   部分成功と区別する。
2. NXPKに`max_total_bytes`を適用し、index/entryの範囲、各entryの実読取長、
   圧縮後サイズ、累積展開量、未知flagをfail-closedで検証する。成功entryの
   manifestにはbounds・実読取長・宣言サイズ・実展開サイズの検証結果を残す。
3. `--resume`とAPI引数を追加し、入力SHA-256・tool name/version・正規化設定から
   `resume_key`を生成する。既存manifestの構造、設定、key、出力全ファイルの
   サイズ/hash、symlink不在を再検証し、改変・欠損・不一致は明示拒否する。
   既存runは削除しない。READMEと回帰テストに契約を記載した。
4. 抽出物とmanifestを同じ一時runに作り、manifest検証後にrunディレクトリ全体を
   `os.replace`で確定する。失敗時は今回の一時runだけを掃除し、既存出力へは触れない。
   `extract --report`で失敗manifestもatomicに永続化できる。
5. `run-manifest.schema.json`をschema version 2の厳格な形へ更新し、追加キーを
   禁止した。標準ライブラリ実装の`validate-manifest`コマンドで複数manifestを
   検証でき、必要なら出力実体のhashも照合する。
6. 小さな合成fixtureで、resumeの改変・欠損・設定不一致、既存出力保護、symlink、
   圧縮率、best-effort partial、入力前後hash、NXPKの総容量・bounds・宣言サイズ・
   zlib・未知flag、manifest改変をテストした。実APK/OBB/NPKはテストへ複製していない。
7. 本節と下記検証表を進捗記録へ追記し、未実装の拡張点を推測で完了扱いにしない。

### 修正後の検証

| Command | Result | Notes |
|---|---|---|
| bundled Python `-m unittest discover -s development/tests -t .` | passed | 25 tests, 1 symlink test skipped because symlink creation is unavailable in this Windows environment |
| bundled Python `-m py_compile` on maintained Python files | passed | `programs/src/asset_extractor` and launcher |
| `python programs/asset_extractor.py validate-manifest ...` | covered | success and tampered-output failure are exercised by tests |
| `scripts/validate-harness.ps1 -SkipDocker` | passed | bundled Python path supplied; PyYAML 6.0.2 installed from `requirements-dev.txt`; hook, skill, unittest checks passed |

### 未実装の拡張点

- split APKのbase判定、4 worker以下の大規模運用、空き容量preflight、JSONL進捗は
  既存計画どおり今後の拡張であり、今回のMVP範囲には追加していない。
- NXPKの未確認形式差分、ゲーム固有のscene関連付け、変換・材質・アニメーションの
  意味的復元、cloudfilesys復号は自動工程へ入れていない。
- 入力が外部プロセスによりhash取得中に繰り返し変わる場合の完全なOSレベルsnapshotは
  標準ライブラリMVPの範囲外であり、前後hash不一致を失敗として記録する安全側に留めた。

## Sol mid修正後再採点

- 再レビューtask: `01a0953c-a0dc-7b42-ac9d-fb64a252c587`
- Luna max修正task: `01a0955a-5a4b-7ba3-a506-7be0bb5a610b`
- Sol mid再採点: **90/100（合格）**。原本不変・fail-closed・atomic run・入力前後hash・
  manifestと実体の相互検証・外部通信なしの必須ゲートはすべてPASS。
- 残る制限は、実APKの同名ZIPエントリを上書き規則なしで拒否すること、改変resumeを
  自動再生成せず拒否すること、OSレベルsnapshot・split APK判定・大規模worker・
  変換/scene復元がMVP外であること。いずれも計画の未実装拡張点として明示した。
