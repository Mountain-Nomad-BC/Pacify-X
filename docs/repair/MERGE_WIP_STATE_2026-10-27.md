# Interrupted merge found in the working tree — 2026-10-27

**Status: the checkout is mid-merge and 20 files are physically corrupted with conflict markers. No engineering work can proceed safely until this is resolved.**

This state was **not** described in the Resume15 handoff, which reported "18 modified + 66 untracked" and HEAD `9583fcd9`. Both figures are stale.

## What is actually there

| Fact | Value |
|---|---|
| HEAD | `e4c6806f` (handoff said `9583fcd9`) |
| `MERGE_HEAD` | present — a merge is in progress |
| Branch being merged in | `codex/rollout-day1-20261024` |
| Merge base | `67827f97` |
| Commits being merged | 8 |
| Staged changes | **794 files, +405,311 / −440,946** |
| Conflicted files | **23** |
| Files containing literal `<<<<<<<` in their bytes | **20** |
| Untracked | 0 |

## How it happened

`git merge codex/rollout-day1-20261024` (the rollout worktree at `5ebc7368`) was started and **left unresolved**. Because the two trees diverged massively from their merge base — both sides rewrote roughly a thousand files — this is a whole-tree reconciliation, not a mechanical conflict fix.

Both sides also **independently added the same files** (`AA` conflicts on `tests/test_project_revision_succession.py`, `tests/test_rollout_inventory.py`, `tests/test_app_local_model_profile_guard.py`), so these are not simple "ours vs theirs" choices.

## Why this matters

- The working tree **cannot run its own gates**. `scripts/build_contract_ownership_registry.py` has 5 conflict hunks and will not import; `scripts/validate_certification_pipeline.py` has 7. Test files that carry required certification suites are equally broken.
- Any test result taken now is **meaningless** — several suites fail purely from syntax errors.
- The runbook explicitly forbids bulk-replacing this tree. Completing this merge would stage ~794 files of wholesale change, which is exactly the "wholesale worktree replacement" it prohibits without per-path adjudication.

## What is NOT damaged

**All prior source repairs survived intact** and are outside the conflict set:

- `runtime/usage_memory.py` — T.I.E. fusion (clean)
- `runtime/semantic_entity.py` — `contract_path()` (clean)
- `runtime/file_lock.py` — process-local exclusion (clean)
- `extension/src/agentHarness/durableTaskState.js` — ported module (clean)
- `contracts/semantic/semantic-entity.schema.json` — stricter contract (clean)
- `tests/test_tie_fusion.py`, `tests/test_semantic_entity_contract.py` (clean) — **27 tests pass**
- Operational ledger — **valid**

Git is fully intact: `HEAD` is clean, and all three conflict stages (base/ours/theirs) are preserved in the index. Nothing is lost.

## The decision, and why it is yours

Two honest options:

**A. Abort the merge** (`git merge --abort`) — returns the tree to clean HEAD `e4c6806f` plus the intact repairs, unblocks all gates immediately, and leaves the rollout reconciliation as a **deliberate, reviewed activity** rather than a half-applied merge. The rollout work stays available at `5ebc7368`.

**B. Complete the merge properly** — 23 real conflicts, ~794 files of wholesale change needing per-path adjudication against `RECONCILIATION_MATRIX.csv`. This is days of work, and it contradicts the runbook's rule against bulk replacement without a decision per path.

**My recommendation is A.** The reason is not convenience: a merge that silently replaces 440k lines is the opposite of the evidence-based reconciliation this project demands, and completing it would invalidate the freezes and receipts built on the current tree. But aborting discards whoever's intent that merge represented, so I am not doing it unilaterally.

**Snapshot taken before any decision:** `.audit-handoff/20261027-merge-wip-065427/` — status, both HEADs, conflict list, and copies of all 23 conflicted working files.
