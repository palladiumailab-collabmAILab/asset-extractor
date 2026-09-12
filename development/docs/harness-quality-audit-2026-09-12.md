# ハーネス品質監査 — 2026-09-12

## 結果

- 初回評価: **78/100**
- 改善後評価: **96/100**
- 合格基準: **90/100**

## 評価基準

| 評価項目 | 配点 | 初回 | 改善後 |
|---|---:|---:|---:|
| 指示構造と優先順位 | 18 | 15 | 18 |
| 開発ワークフローと自律性 | 14 | 12 | 14 |
| モデル振り分けとコンテキスト効率 | 14 | 8 | 13 |
| skillの適用範囲と段階的開示 | 14 | 12 | 13 |
| 安全性と秘密情報の保護 | 14 | 11 | 13 |
| Git/GitHub運用の信頼性 | 10 | 9 | 9 |
| 自動検証と回帰テスト | 6 | 4 | 6 |
| 移植性と文書品質 | 10 | 7 | 10 |
| **合計** | **100** | **78** | **96** |

## 初回評価が低かった原因

1. subagentの利用で総トークンを削減できるように読める記述があった。OpenAI Docsでは、subagentは通常より多くの総トークンを使い、主な利点は並列化と主スレッドから雑音を分離することだと説明されている。
2. `.githooks/pre-commit`が`100644`で記録されており、UnixのGitクライアントでは実行されない可能性があった。
3. 秘密ファイル名の規則が、安全な`.env.example`まで拒否していた。
4. 秘密鍵検出の正規表現が、追加行の先頭から始まるマーカーを見逃していた。
5. CIと再現可能な検証コマンドがなく、これらの不変条件を継続的に保護できなかった。
6. 改行コードの規則がなく、WindowsとLinux間でshell scriptが壊れる余地があった。
7. 最初のCI定義ではpip cacheの依存ファイルを明示せず、旧Node runtimeのActionsも使っていたため、初回実行が失敗した。

## 実施した改善

- `AGENTS.md`と`README.md`のsubagentに関するコスト・コンテキスト説明を修正した。
- OpenAIのAGENTS.md文書に基づき、指示探索と優先順位を明文化した。
- pre-commitの2件の判定不具合を修正し、環境変数テンプレート、秘密ファイル名、秘密鍵マーカー、空白エラーの挙動テストを追加した。
- shell entry pointを実行可能として記録し、`.gitattributes`と`.editorconfig`を追加した。
- PyYAMLを使うskill validator、Dockerを使うWindows向け検証入口、読み取り専用のGitHub Actions検証を追加した。
- GitHub ActionsをNode 24対応版へ更新し、pip cacheの依存ファイルを明示した。
- `.env.example`、`.env.sample`、`.env.template`を保持できる保守的な`.gitignore`を追加した。

## 100点にしなかった理由

- pre-commitの秘密情報検査は軽量なヒューリスティックであり、高リスクなリポジトリで使う専用secret scannerの代替ではない。
- skill構造とリポジトリの不変条件は検証するが、代表的な開発タスクを使ったagentの振る舞いevalはまだない。
- Sol/Lunaの振り分けは今回の要件に最適化しており、あらゆるCodex環境の普遍的な既定値ではない。

## 一次資料

- [OpenAI: Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [OpenAI: Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [OpenAI: Model guidance](https://developers.openai.com/api/docs/guides/latest-model)
- [OpenAI: GPT-5.6 Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol)
- [OpenAI: GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
