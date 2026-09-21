# Project baseline index

このファイルは互換性のための索引です。**通常タスクで全文を読む前提ではありません。** 対象変更に対応する文書だけ読みます。

- 仕様の正本・durable behavior: `docs/baselines/specifications.md`
- Docker / 再現環境: `docs/baselines/docker.md`
- GitHub Actions / remote quality gate: `docs/baselines/github-ci.md`
- Python lint / format / Ruff: `docs/baselines/python-ruff.md`

複数領域を実際に変更するときだけ複数文書を読みます。framework、DB、service topology、物理ディレクトリ構成などはプロジェクト固有であり、このbaselineから一律強制しません。

下流repoでは共通文書を upstream-managed とし、project-specific な規則・例外・コマンドは `AGENTS.project.md` または明示的な project docs に置きます。
