# Docker reproducibility

Docker環境を追加・変更する、または再現性を受け入れ条件として確認するときだけ使用します。

- 実行可能ソフトウェアは、canonical verification に必要な依存とコマンドを再現できる Docker 経路を持つ。
- runtime 実行がプロジェクトの成果に含まれる場合、主要実行経路もDockerで再現できるようにする。
- host 実行は高速な開発経路として使ってよいが、Docker再現性が明示要件なら host-only success を代替にしない。
- 単一containerで足りるprojectにComposeを強制しない。複数serviceの協調起動が必要な場合だけ orchestration を追加する。
- Docker要件からmicroservice、frontend/backend分離などのarchitectureを推測しない。
