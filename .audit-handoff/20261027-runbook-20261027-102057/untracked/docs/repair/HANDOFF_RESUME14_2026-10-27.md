# Resume14 handoff — 2026-10-27

**State: INCOMPLETE. No release certificate. No independently reviewed closures (0 of 105).**

Written by the successor that received Resume13. Everything marked `VERIFIED_NOW` below was executed against this checkout while writing this file. Everything marked `INHERITED` is a prior claim that this handoff did **not** re-execute — treat it as unverified until you run it.

## 1. How to start

| Item | Value |
|---|---|
| Checkout | `C:/Users/Ben/Documents/bootstrap_project/Pacify-X` |
| Branch | `codex/repair-reconcile-20261025` |
| HEAD at handoff | `9583fcd9` (local; not pushed) |
| Reference worktree | `C:/Users/Ben/Music/Pacify-X-rollout-20261024` @ `5ebc7368`, unchanged |
| Status ledger | `docs/repair/REPAIR_STATUS.json`: 105 cards, `reviewed_closed: 0`, zero cards `closed` |
| Plan | `docs/repair/ROLLOUT_COMPLETION_PLAN.md` (R01–R14, definitions of done) |
| Last checkpoint / admission | checkpoint `…36232` (`VERIFIED_NOW`) / sessions `repair-resume13-host-discovery` (36231) and `repair-resume13-release-completion` (36228) |

**`AGENTS.md` IS PRESENT AND OUTRANKS THIS DOCUMENT** (4102 bytes, `VERIFIED_NOW`). Read it first. It requires: effects declared and guarded per effect (`read`/`write`/`execute` may share one admission scope; `network`/`install`/`service`/`destructive` each need their own single-effect admission); a registered campaign order with repair-only work while intake is open; exactly one full profile + one validation and no speculative broad runs; owned workspace/child-process registration and reconciliation; and explicit user closure of staged intake. A task assignment or approval is **not** a work admission.

One correction for the record: an earlier draft of this handoff claimed `AGENTS.md` was missing, based on a failed resolution. It was present all along. Verify path claims directly rather than inferring absence from a lookup error — that mistake is precisely the class of unverified assertion this project keeps having to retract.

Dirty tree is inherited and must be preserved: **10 modified + 1 new doc** after this segment (`VERIFIED_NOW`). Earlier drafts of this file said 23+65 and then 25 — both were stale counts, not measurements of this tree. Re-measure before you edit; do not trust any count in prose, including this one. Do not `git reset --hard`, `clean`, `checkout -- .`, bulk-replace, or delete inherited untracked files. Snapshot `.audit-handoff/20261026-resume9-*` exists; take your own before editing.

## 2. What changed and is now actually verified

**Certification coverage is structurally closed.** `certification_coverage(ROOT)` returns `valid: True`, `required_count: 43`, `missing_membership: []`, `missing_files: []`, `duplicate_members: []` (`VERIFIED_NOW`, live call — not the saved `evidence/resume13-coverage.json`). This supersedes Resume9's blocker: the two suites that were absent (`tests/test_rollout_inventory.py`, `extension/tests/billing-settlement-audit.test.js`) were ported in source between segments, together with the supporting `scripts/rollout/*` and `src/agentHarness/durableTaskState.js`. Structural membership is **not** execution, installed operation, or certification.

**The event-bus lock defect is fixed** (my earlier segment). `test_concurrent_batch_and_single_publish_keep_one_chain` failed with `FileLockTimeout` on 2 of 3 runs and `test_file_lock_contention.py` hung. Two causes: Windows `msvcrt` byte-range regions are owned by the *process*, so sibling threads contend with their own process; and `_heartbeat_once` held the non-reentrant `_metadata_guard` then re-entered it through `_write_record`. Fixed by process-local per-file-identity exclusion claimed before any byte-range attempt, level-triggered `notify_all()` handoff, and a re-entrant metadata guard. Receipts: `evidence/resume9-lock-red-before.log`, `-residual-red.log`, `-lock-timing-probe.py`, `-file-lock-suite.log` (10 pass), `-event-full.log` (42 pass), `-event-ledger-neighbours.log` (23 pass), `-contract-roundtrip.log` (195 schemas / 0 failures). The suite `tests/test_file_lock_thread_custody.py` now exists and is bound to the `event-integrity` section.

**Status ledger now spans the real denominator.** `REPAIR_STATUS.json` had carried only a hand-maintained five-card subset, leaving 100 findings with no disposition. It is regenerated from the kit queue: 105 unique cards, all `reviewer: UNASSIGNED`, `reviewed_closed: 0`, none closed. Pre-sync copy at `evidence/resume9-REPAIR_STATUS.pre-sync.json`; generator `evidence/resume9-status-sync.py` (refuses unmapped kit states rather than guessing). **Queue states are evidence levels, never review.**

## 3. The one open source failure — and why you must not "fix" it by hand

`VERIFIED_NOW`: `rebuilt = 203` ownership records vs `committed = 196`.

- `only_committed`: none, `content_diff`: 0 — the published registry is a strict, uncorrupted **subset**.
- `only_rebuilt` (exactly 7): `contracts/models/generation-bound-verdict`, `member-execution-input`, `model-branch-artifact`, `model-execution-group`, `model-group-preparation`, `operations/remote-provider-profile`, `remote_model_attachment`.

So Resume13's reported asymmetry is real and has a precise, benign explanation: published ownership is stale only for the newly added model-group contracts. Consequently `tests/test_contract_ownership_registry_source.py::test_build_needs_no_published_registry` fails (**1 failed, 21 passed**, `VERIFIED_NOW`).

**Do not regenerate it now.** Plan step R14.3 freezes the revision first and reconciles generated projections from the frozen source in canonical order. Regenerating mid-intake would publish projections for a revision that is about to change, and would hide the drift from whoever reviews the freeze. The failure is the correct, honest signal — preserve it. It also means `provider_route_scan` will report `index_stale` for any file you edit, by design (`scanned_roots` is checkout-scoped), so `validate_registry` staying red is expected until the freeze.

## 3b. Namespace migration is atomic, not per-consumer (`REPRODUCED_THIS_SESSION`)

Added `control_path(root, *parts)` and `resolve_project_management(root, *parts)` to `runtime/engineering_os_paths.py`. `control_path` is the sanctioned write target the module's own docstring already promised but never exported; `resolve` can legitimately return the legacy tree and must not be used to pick a write authority. Both refuse absolute or `..` segments.

I then tried the obvious migration — point `tool_intake.py` at `control_path()` — and **it broke state resolution**: `commissioning` writes `.engineering-bootstrap/project-management/state.json`, so the canonical tree stayed empty and `lifecycle_status` could no longer find the state. Reverted; `tool_intake.py` keeps its literal path and now carries the reason.

Measured evidence for why: **61 of 1435** test-evidence JSON receipts embed the literal `.engineering-bootstrap/test-evidence/` path. So migrating the control directory is one atomic change across the commissioning owner, its callers and those receipts — not a per-consumer edit. Probe retained: `evidence/resume14-namespace-probe.py|.log`.

Because of this, the 2 open `NAMESPACE_MIGRATION_REVIEW_REQUIRED` records stay open deliberately. Closing them by switching one consumer would have looked like progress and silently split the state.

## 4. Real blockers (authority, not engineering)

1. **No trusted signer.** No genuine signed successor owner policy, evidence, or authorization has been found in admitted roots. Public trusted keys exist in `release-trust.json` / `effect-grant-trust.json`; private keys are explicitly repository-external. Existing host SSH keys do not match repository release-trust fingerprints, and no private key contents were read. **Never** fabricate a key, relax trust, reuse a fixture signature, or copy a historical artifact as new authorization. `.engineering-bootstrap/test-evidence/px-os-1067-succession.json` is a September handoff, not authorization.
2. **Governed sections still phase-blocked** by the historical September `installed_operational` campaign. Do not edit its phase or its receipts to unblock. The successor must be commissioned through native signed authority first.
3. **No live catalog/inference proof.** A real localhost probe failed with a `URLError` timeout and — importantly — was issued without a declared network effect, which is recorded in `evidence/resume13-host-catalog-timeout.json`. The crash was repaired so the catalog now reports sanitized `local_catalog_status: runtime_unreachable_or_invalid` with no available models; **actual health has not been re-proved after that fix.** Any further probe needs a separate explicit network/service admission and owned process custody. Do not start `llama-server.exe` under an ordinary repair admission; do not auto-load the 30B asset (`.pacify-x/models/qwen3-30b-a3b/...`, ~21.7 GB) — the 4B control profile `control-qwen35-4b-cpu-q6` is the intended light target, and even that needs admission.

## 5. Remaining work, in order (nothing here is done)

1. **R01 finish.** 12 contract dependency reviews and 2 namespace/distribution migrations remain (214-candidate adjudication: 188 exact, 2 JSON-equal, 1 stronger target authorization, 9 component-tested/generated-pending, 12 dependency reviews, 2 namespace migrations).
2. **Model-group completion.** WorkflowStudio group node/effect transport, AgentRuntimeController mesh orchestration, remote placement/member-outcome owners, independently verified convergence, object-local TIE usage-memory. `model_group_preparation` imports `fuse_tie_experience`, which is **missing** from the current `usage_memory` — that path is not commissioned; do not copy the reference usage owner without reviewing native leases/intents and per-object attribution.
3. **WorkflowStudio approvals.** Review every caller and consumed signed capability before integrating host-boundary approvals. A magic `approved_by` string must not become standalone authority. Resolve its forward namespace against current immutable Studio records instead of rewriting history.
4. **R02–R11.** Hostile path/reparse/hardlink attacks, exclusive publisher, WAL fault recovery, Python↔Node billing receipt boundary, cancellation/lifecycle, providers, memory/NSAI, scheduling, model leases. Exercise real callers, not helpers.
5. **R13.** Additional standalone kit, after first-kit acceptance, deduplicated by ID with explicit links.
6. **Phase C, strictly last.** Real successor/freeze → one canonical reconciliation → current governed sections → exactly one `test-profile run full` and one `validate` → package → clean-room install → real installed operation → independent review → native finalizer certificate → merge/push/VSIX. The user has explicitly asked for merge and VSIX **after** validation; that ordering is not permission to skip prerequisites.

## 6. Discipline that has already prevented two false claims

- Never equate unit green = operating = installed = reviewed = certified. This handoff exists partly because a "green" concurrency claim was actually failing 2 of 3 runs.
- Record the **exact** failing state before fixing, and retain it (`red-before`, `residual-red`). Two of my retained logs showed *different* defects; the second was only found because the first was kept.
- Verify required-test membership by executing the live predicate, not by reading a saved evidence JSON — the saved coverage file and the live result can diverge.
- Use the retained supervised runner `.tmp/resume10/run_segment.py` (source archived at `evidence/resume12-owned-runner.py`); set `TMP`/`TEMP`/`TMPDIR` to the registered workspace; inspect child exit code, process-tree closure and resource proofs. Explicit UTF-8 for every authored read/write — default cp1252 will corrupt source.
- Long fsync-heavy suites exceed a 120-second foreground command limit; run them supervised and inspect the log, and do not leave detached `Start-Process` children that swallow output.
- Update all four surfaces after each bounded segment: `SESSION_STATE.md`, `TRACKING_LOG.md`, `REPAIR_STATUS.json`, and kit `tracking/EXECUTION_LOG.jsonl`.

## 7. Immediate next command sequence

```powershell
$repo = 'C:\Users\Ben\Documents\bootstrap_project\Pacify-X'
Set-Location $repo
Test-Path AGENTS.md                                  # re-check governing instructions
git rev-parse HEAD; git status --porcelain=v2 --branch
python scripts/operational_gap_ledger.py validate     # expect exit 0
.\.venv-repair\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); from pathlib import Path; from scripts.validate_certification_pipeline import certification_coverage as c; r=c(Path('.').resolve()); print(r['valid'], r['required_count'], r['missing_files'])"
python .tmp\resume9\run.py red-ownership tests/test_contract_ownership_registry_source.py   # expect the 1 known intentional failure
```

Then: take a checkpoint and predecessor-bound admission with separately guarded read/write/execute effects, snapshot the dirty tree, and start at §5 item 1. Do not begin with a broad test sweep — it tells you nothing that the specific R01 dependency reviews do not.
