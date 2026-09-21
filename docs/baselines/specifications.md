# Canonical specifications

durable な製品・システム要求を変更または解釈するときだけ使用します。

- 既存の正本がなければ `docs/specs/` を標準位置とする。既存に明確な正本があるなら二重化しない。
- 仕様は「何が真であるべきか」、architecture は「どう構成するか」、Issue/進捗は「今何を変えるか」、history は「過去に何を決めたか」を扱う。
- observable behavior、data contract、外部interfaceなど requirement-sensitive な変更では、関連仕様だけを先に読む。
- 実装と仕様が矛盾する場合、どちらかを黙って正しい扱いにせず、どちらがcurrentか解決する。
- 仕様変更が依頼範囲なら、実装だけでなく正本仕様も整合させる。

新規の仕様索引が必要な場合は `templates/project-specs/README.md` を起点にできます。
