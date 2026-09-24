# Testing governance

テストは実装の自己採点ではなく、仕様・契約・既知の正解・不変条件に対する独立した証拠として扱う。ただしテスト自体も誤り得るため、固定化ではなく変更権限と根拠を管理する。

## Core rule

テスト失敗を見つけても、実装に合わせて既存の oracle を自動修正しない。まず次のいずれかに分類する。

1. **implementation bug** — 実装が仕様・契約・既知の正解に反する。
2. **test bug** — テストの期待値、前提、fixture、mock、assertion が独立した根拠に反する。
3. **specification unresolved** — 実装とテストのどちらが正しいかを決める上位根拠が不足または矛盾している。

分類できない状態でテストと実装を同時に変更して green にしない。

## Independent oracle

既存テストの意味を変える変更には、実装とは独立した根拠を最低1つ要求する。

- canonical specification / acceptance criterion
- API / schema / protocol contract
- known-good input/output or reference implementation
- domain invariant or mathematically derived property
- independently reproduced bug report or external conformance evidence

「現在の実装がそう動く」「この変更ならCIが通る」は根拠にならない。

## Test classes

### Developer tests

実装担当が通常追加してよいもの。

- 新しい unit test
- 新しい局所 fixture / mock
- 実装詳細を検証する補助テスト

ただし既存の期待値や意味を変更する場合は protected-oracle change として扱う。

### Protected oracle

次は成功条件を変え得るため、通常の実装変更から分離する。

- 既存 assertion / expected value
- regression / acceptance / contract tests
- golden files / snapshots / reference outputs
- failure を消す skip / xfail / disable / deletion
- fixture / mock の変更で期待される意味や入力分布を変えるもの
- threshold / tolerance / grader / evaluation criterion の緩和

## Sol / Luna responsibility

**Sol**

- 要求・制約・acceptance criteria の整理
- 実装計画とテスト設計
- protected oracle の所有と変更判断
- test bug / specification unresolved の裁定
- 難しいデバッグ、最終レビュー、統合判断

**Luna**

- Sol が境界を定めた実装
- 機械的変更、局所デバッグ
- 新規 unit test の追加
- test / lint / build の実行と結果収集

Luna は green 化のために protected oracle を変更しない。test bug または specification unresolved を疑った場合は、失敗を保持して根拠と変更案を Sol に返す。

GitHub 作業では、Luna が protected-oracle change を具体化する必要がある場合も、専用の提案 branch / PR に留め、実装変更と同時に統合しない。merge 判断は Sol のレビューまたはユーザーの明示判断に戻す。

## Failure workflow

```text
Sol: requirements / plan / test design
  -> Luna: bounded implementation + developer tests
  -> Luna: run tests
     -> implementation bug: Luna fixes implementation and reruns
     -> suspected test bug: preserve failure, attach independent evidence, return proposal to Sol
     -> specification unresolved: stop semantic changes and return conflict to Sol
  -> Sol: review evidence and decide whether implementation, test oracle, or specification changes
  -> protected-oracle change, if justified: separate review unit / PR
  -> final verification against the resulting canonical criterion
```

## Review record

Protected-oracle change の提案には最低限次を残す。

- failing test / criterion
- classification: test bug or specification unresolved
- independent evidence
- why the old oracle is wrong or obsolete
- exact oracle change
- whether the canonical specification also changes
- regression risk and verification plan

テスト変更の目的は「通すこと」ではなく、「より正しい oracle に更新すること」である。
