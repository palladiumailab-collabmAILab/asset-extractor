# Design

## Purpose

許可されたAPK/OBB/NPK等の資産を、原本を変更せず、監査可能かつ再実行可能な形で棚卸し・抽出・変換する。

## Design principles

- **原本不変。** 入力は読み取り専用として扱い、処理前後のハッシュで不変性を検証する。
- **再現性と監査性を優先。** 各runにmanifest、ハッシュ、設定、tool/version、結果statusを残す。
- **fail-closed。** 未知形式、未知flag、境界違反、整合性不一致は推測で継続しない。
- **段階的処理。** 取得、抽出、形式判定、変換、レンダー、照合を分離し、各段階を独立検証可能にする。
- **best-effortと成功を混同しない。** complete / partial / failedを明示的に区別する。
- **アクセス制御を回避しない。** DRM、認証、root、run-as等による保護回避は設計対象外とする。

## Non-goals

- 抽出payloadの実行。
- 認証・DRM・アクセス制御の回避。
- 不明データから名前、UV、Tex0等を推測して書き換えること。
- 大容量原本や生成物をGitHubへ保管すること。

## Architecture intent

`input/` は原本と入力由来情報、`output/` はrun成果物、`programs/` は保守対象プログラム、`development/` は計画・schema・fixture・test・evidenceを担当する。

実装計画は `development/PLAN.md`、pipeline方針は `development/NETEASE_ASSET_PIPELINE_PLAN.md`、machine-readable contractは `development/schemas/` を正本とする。
