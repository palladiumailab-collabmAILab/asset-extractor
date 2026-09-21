# Python / Ruff baseline

Python lint / format設定または品質ゲートを追加・変更するときだけ使用します。

- maintained Python では Ruff を標準 lint / format gate とし、少なくとも `ruff check ...` と `ruff format --check ...` をcanonical validationへ含める。
- target Python version、line length、lint families、exclusion、generated-code handling はproject-localに設定する。
- Flake8 / isort / pyupgrade / Black など責務が重複する常設gateは、明確な理由がなければRuffへ集約する。
- pytest、mypy、pyright、security scanner、domain validatorなど直交する検証は必要に応じて保持する。
- Ruff導入と無関係な機能変更を、whole-repo reformatと同じ変更に混ぜない。
