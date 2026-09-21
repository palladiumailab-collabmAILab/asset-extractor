# GitHub CI baseline

GitHub Actionsを追加・変更する、またはremote verificationを要求されたときだけ使用します。

- GitHubで管理する実行可能ソフトウェアでは、GitHub Actionsを標準のremote quality gateとする。
- workflowは原則として pull request と default branch push で、プロジェクトに意味のある lint / format / test / type check / build / invariant / domain validator を実行する。
- local / Docker checks は preflight。GitHub反映が依頼範囲なら、対象commitまたはPRの期待されるActions結果を確認する。
- expected workflow が存在しない、実行不能、pending、または失敗なら remote verification success と報告しない。
- green化のためだけに `continue-on-error`、test skip、coverage/validation threshold低下、required check削除を行わない。
- branch protection / ruleset 等のrepository settings変更は明示承認が必要。
