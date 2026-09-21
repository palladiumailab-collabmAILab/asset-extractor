# Codex Software Development Harness

システム・開発者指示、ユーザーの明示依頼、現在地に近い `AGENTS.override.md` / `AGENTS.md` を優先します。このファイルは常時読む最小ルータです。

## 正本

- 共通ハーネスの正本は `palladiumailab-collabmAILab/codex-dev-harness`。
- 下流へコピーした共通ファイルは upstream-managed とし、プロジェクト固有規則は `AGENTS.project.md` 等へ分離する。
- 共通規則の変更は正本で検証してから pinned revision で下流へ同期する。

## モデルプロファイル

実行中のモデルに対応するものを **1つだけ** 読みます。

- GPT-6 Astra: `profiles/astra/AGENTS.md`
- GPT-5.6 Sol / Luna: `profiles/sol-luna/AGENTS.md`
- その他: モデル固有プロファイルを推測で流用しない。

## 共通不変条件

- 依頼された成果、明示制約、受け入れ条件を変更しない。
- durable な仕様変更では、関連する正本仕様だけを先に確認する。
- test / lint / build / 評価は証拠であり成果そのものではない。合格のためだけに条件や評価器を弱めない。
- 最小の変更面に限定し、依頼外の機能・依存・大規模リファクタを追加しない。
- 既存の未コミット変更を保持し、破壊的 reset / clean / force push を既定にしない。
- 秘密情報を出力・コミット・外部送信しない。依頼のないデプロイ、課金、削除、権限変更、外部書込みを行わない。
- 同じ情報を目的なく再読込せず、状態変化のない同一検証を反復しない。

## 条件付き参照

必要な項目だけ読みます。通常実装で `docs/project-baseline.md` 全体を先読みしません。

- 仕様の正本・仕様変更: `docs/baselines/specifications.md`
- Docker / 再現環境を変更・追加: `docs/baselines/docker.md`
- GitHub Actions / remote quality gate を変更・確認: `docs/baselines/github-ci.md`
- Python lint / format / Ruff を変更・追加: `docs/baselines/python-ruff.md`
- task contract / evaluation / optimization semantics を変更: `docs/harness-architecture.md`
- セッション間 handoff が必要: `templates/codex-progress.md`
- モデル別タスク依頼を組み立てる: `templates/task-prompts/`

## Skill 発火条件

- `repo-research`: 未知のrepoで複数モジュールを横断して入口・依存・実行経路を特定するとき。
- `github-operations`: branch / commit / push / Issue / PR / CI / remote mutation を明示依頼されたとき。
- `self-improvement`: baseline と評価基準を固定して agent / prompt / tool / workflow を反復比較するとき。
- `long-running-work`: 通常の1実装パスで完了せず、複数の大きな段階またはセッション間handoffが必要なとき。
- `reverse-engineering`: 許可された opaque / legacy / binary / protocol を互換性・移行・診断・防御目的で解析するとき。

該当する `SKILL.md` だけ読み、全skillを事前読込しません。
