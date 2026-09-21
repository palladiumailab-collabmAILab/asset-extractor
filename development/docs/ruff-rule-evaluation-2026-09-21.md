# Ruff rule-family evaluation — 2026-09-21

## Scope and command

The maintained Python gate covers `programs`, `scripts`, and `development/tests`.
The repository uses Ruff 0.8.4 from `requirements-dev.txt`; `programs/legacy` and
`programs/vendor` remain excluded by `pyproject.toml`.

Each candidate family was evaluated independently from the baseline `E`/`F`
configuration with:

```text
ruff check --select FAMILY --output-format=concise programs scripts development/tests
```

## Results

| Family | Findings | Representative findings | Decision |
|---|---:|---|---|
| `I` | 45 | `I001` import blocks are unsorted or unformatted | Keep disabled. All findings are mechanical import-order churn across maintained files; no defect-prevention signal justifies mixing that migration into this task. |
| `UP` | 10 | `UP035` imports from `collections.abc`, `UP017` uses `datetime.UTC`, `UP038` modernizes `isinstance` | Keep disabled. The family mixes compatibility modernization with one unsafe fix and would require a separate, reviewed migration. |
| `B` | 9 | `B905` requires an explicit `strict` choice for `zip`; `B007` catches an unused loop variable | Adopt. The findings expose silent truncation risks at data-association boundaries and one misleading loop variable. |
| `SIM` | 12 | `SIM117` nested contexts, `SIM102` nested conditionals, `SIM105` suppressible exception | Keep disabled. These are readability preferences with context-dependent trade-offs; the bounded migration is not worth enabling repository-wide here. |

## Adopted migration

The `B` findings are fixed without blanket ignores:

- paired collections with an established equal-length contract now use
  `zip(..., strict=True)`;
- the adjacent-range sliding-window check explicitly uses `strict=False` because
  its right-hand sequence is intentionally one item shorter;
- the unused `tool_name` loop variable was removed by iterating over values.

The existing test, coverage, type, schema, and format gates remain unchanged.
Future `I`, `UP`, or `SIM` adoption should be a separate migration with its own
reviewable diff and representative behavior tests.
