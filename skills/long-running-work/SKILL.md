---
name: long-running-work
description: Structure long-running or multi-session software work into small verifiable units with a compact handoff. Use only when the task is too large for one clean implementation pass or must continue across sessions.
metadata:
  short-description: Split and hand off long-running work
---

# Long-running work

Use this skill only when the work is expected to span multiple substantial stages or sessions.

## Workflow

1. Define the overall goal and acceptance criteria.
2. Split the work into the smallest independently verifiable tasks. Keep only one active implementation boundary at a time.
3. Prefer the repository's existing progress or planning file. This repository uses `development/work/codex-progress.md` for handoff state.
4. After each completed unit, record only:
   - current branch/revision and working-tree state;
   - completed work;
   - next smallest task;
   - verification commands and results;
   - decisions that constrain later work;
   - unresolved risks or unknowns.
5. Before ending a session, remove unrelated generated artifacts and leave the repository in a state from which the next agent can continue without reconstructing hidden context.

## Context discipline

- Do not paste large logs, full files, secrets, asset corpora, or conversation transcripts into the handoff.
- Link to repository files and record exact commands/results instead of duplicating their content.
- Do not keep stale plans after implementation has changed; update or delete obsolete handoff entries.
- If the remaining work fits in one normal implementation pass, stop using this skill.
