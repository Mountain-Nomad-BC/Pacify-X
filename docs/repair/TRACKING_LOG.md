# Repair Tracking Log

| PX-AUD | Status | Files | Notes |
|---|---|---|---|
| 003 | IMPLEMENTED | runtime/gremlin/host_enforcement_backend.py | partial freeze patch applied |
| 014 | IMPLEMENTED | extension/scripts/run-operational-ui-walk.js | win32 path containment |
| 050 | IMPLEMENTED | (partial) | zero budget propagation |
| 069,070,073 | IMPLEMENTED | runtime/memory_broker.py, memory_vault.py | validation |
| 086,088,089 | IMPLEMENTED | runtime/event_ledger.py, operational_event_bus.py | ledger/bus |
| 038 | IMPLEMENTED | harnessController.js, registerAgentConsole.js | conclusion hash |
| 052-055 | PARTIAL | openaiCompatible.js, ollama.js | streaming rewrites rejected |

## Session 2 — 2026-10-25 (resumed)

| Gate | Command | Result | Evidence |
|---|---|
| Snapshot | `git status --porcelain=v2 --branch`, `git worktree list --porcelain`, `git branch -avv`, `git log` | unchanged from session 1; archives in `.audit-handoff/` verified (31 + 3 entries) | `.audit-handoff/*-20261025-114100.*` |
| Env | `.venv-repair/Scripts/python.exe` (3.14.5, pytest 9.1.1) + `pyyaml==6.0.3` from pinned cache | collection errors (8, missing `yaml`) resolved | `docs/repair/evidence/` |
| Ownership targeted | `pytest tests/test_contract_ownership_registry.py -q` | **2 passed** | `docs/repair/evidence/ownership-registry-baseline.log` |
| G01 generator audit | `build(ROOT)` vs `registry/contract_ownership.json` | equal (180/180) **but self-referential** — no explicit rule needed | `docs/repair/evidence/contract_ownership-built.json` |

## Session 3 ? isolation and ownership checkpoint

Protected64source files across both trees, retained binary diffs and hashes; branched bootstrap to codex/repair-reconcile-20261025. Focused command (clone isolation + contract ownership + declared suites):19passed in59.46s; evidence resume3-isolation-ownership.log. Clone copies independent inodes; no source guard weakened. Generator changes remain source-tested, not independently closed. Auditing adjacent builders and adding a mandatory source-authority section next.

Source-authority checkpoint:27focused tests pass (`evidence/resume3-source-authority-focused-green.log`); corrupt previous-map RED preserved. Mandatory source-authority gate blocks before execution because historical September campaign is installed_operational. No state bypass or historical rewrite. New105-row REPAIR_STATUS.json tracks0reviewed-closed;7cards have14passing inherited Node checks but remain IMPLEMENTED_UNVERIFIED. Reconciliation inventory967paths is evidence only; no wholesale merge has occurred. Rollout billing controller now records usage before cancellation/status discard;32Node neighbors pass, governed billing gates running. Bootstrap cascade run remains active; do not claim it green.

Required-section policy check passes (1test,41.63s): evidence/resume3-section-policy-focused.log. Registry diagnosis isolates provider_route_scan.json index_stale; root Orchestrator rejects before handler resolution through this legitimate guard. Preserve the blocker until source freeze/reconciliation. Large cascade run is diagnostic only: source changes overlapped it and no immutable current-gate claim is allowed.

## Session 4 — 2026-10-25 (resumed from updated continuation handoff)

| Gate | Command | Result | Evidence |
|---|---|---|---|
| Trust anchor | `git rev-parse HEAD`, `log`, `status -v2` on both worktrees | bootstrap now on `codex/repair-reconcile-20261025` @ `6174918a`; rollout @ `5ebc7368`; both dirty — preserved | `.audit-handoff/20261025-resume4/status-main-20261025-160842.txt` |
| Pre-change backup | `git diff --binary` + `git ls-files --others` -> python tarfile | 86/86 untracked members verified readable (first tar attempt was truncated and discarded) | `.audit-handoff/20261025-resume4/` |
| Succession RED reproduction | `pytest tests/test_project_revision_succession.py -q` | 1 failed, 37 passed — `ModuleNotFoundError: jsonschema` (test-env gap, not source) | `evidence/resume4-succession-before.log` |
| Succession after env fix | `pytest tests/test_project_revision_succession.py tests/test_revision_activation_e2e.py -q` | **40 passed** | `evidence/resume4-succession-after-dep.log` |
| Structural cascade (restart of the interrupted run) | `pytest test_structural_clone_isolation test_ownership_source_independence test_python_surface_boundaries test_repository_scope test_test_profiles test_completion_status test_structural_integrity -q` | RUNNING — RED at ~82%; not green | `evidence/resume4-cascade-stdout.log` |

No assertion was weakened. The resume3 note claiming the `'digest mismatch'` expectation was a live defect
does not reproduce on the current tree: the test already accepts `digest mismatch|source identity binding`.

Batch 2 (G01 / source-authority) — generated-artifact drift repaired at canonical generators, NOT hand-edited:

| Artifact | Generator | Exit | Before -> After |
|---|---|---:|---|
| `registry/contract_ownership.json` | `scripts/build_contract_ownership_registry.py` | 0 | 184 records, all 4 `contracts/project_revision_succession/*` now present with owner `runtime/project_revision_succession.py` / `revision_succession_runtime_boundary` (rule pre-existed; committed registry was stale) |
| `registry/provider_route_scan.json` | `scripts/build_provider_route_index.py` | 0 | regenerated (`index_stale` resolved) |
| `registry/python_surface_ownership.json` | `scripts/build_python_surface_ownership.py` | 0 | regenerated |
| `registry/effect_surface_ownership.json` | `scripts/build_effect_surface_ownership.py` | 0 | regenerated |
| `registry/python_dependency_ownership.json` | `scripts/build_python_dependency_ownership.py` | 0 | regenerated |
| `registry/artifact_reachability.json` | `scripts/build_artifact_reachability.py` | 0 | regenerated |
| `registry/build_claims.json` | `scripts/build_claims.py --apply` (then `--check`) | 0 / 0 | regenerated; check mode clean |
| `registry/test_group_index.json` | `scripts/build_test_group_index.py` | 0 | regenerated |

Evidence for the ownership half: `evidence/resume4-ownership-after-succession.log` (all green) and
`runtime.contracts.validate_contract_corpus` -> valid, 184/184 owned, 0 errors.

Root cause note: the prior agent added the succession ownership rule to the generator source but never
re-ran the generator, so the committed registry stayed stale while the rule "existed". This is exactly
the failure mode the session-2 `test_build_needs_no_published_registry` regression was built to catch;
it did catch it (structural integrity failed closed) rather than being masked.

Verification run for the repaired artifacts (`test_structural_integrity`, `test_generated_artifacts`,
`test_config_and_registry`, `test_ownership_source_independence`,
`test_contract_ownership_registry_source`) -> `evidence/resume4-structural-after-regeneration.log`.
RUNNING at time of writing; RED markers observed. Not green; awaiting final counts.

Batch 3 (A + C, user-approved) — duplicate logic removed at its owners; no allow-list entry added.

C: the unreviewed duplicate was NOT the file I first suspected. `_logic_duplicates` reported
`tests/test_memory_broker.py::{_record,_plan}` vs `tests/test_memory_broker_regression.py::{...}`
— byte-identical copies in two PX-AUD regression modules. The scheduler pair (`test_scheduler_
regression.py` 074 vs `test_scheduler_path_regression.py` 076) duplicated `_snapshot` the same way.
Fix: single canonical copy in the new `tests/support/fixtures.py` (explicit package, values byte-for-byte
as the audits specify); all five owners import it. `_snapshot` bodies delegate; the recovery module's
repeated admission-telemetry literal was centralised as `telemetry()`.
Result: `_logic_duplicates` -> 212 classified groups, **0 unreviewed**; 39 tests green across the
six PX-AUD modules (`evidence/resume4-shared-fixtures.log`).

A: reached, ownership did NOT need a policy entry. `structural_integrity.reachability` now PASSES —
the two-owner condition was satisfied by the succession contracts shipping with correct canonical
ownership once the registry was regenerated from source.

Additional generated-artifact drift cleared at canonical generators (chained: test sources -> index ->
reachability): `test_group_index`, `artifact_reachability`, `python_surface_ownership`,
`python_dependency_ownership`, `provider_route_scan`. Root cause of the last index drift was an
uncommitted change to `runtime/test_profiles.py` from the inherited succession port, not a bug.
`validate_generated_artifacts` -> **21/21 checks OK**. `audit_structural_integrity` -> 14/15 categories
PASS; the only remaining failure is the intentionally-red `markers` audit (3 unreviewed incomplete
findings), which must stay red until those findings are actually repaired.

Also fixed: `scripts/build_contract_ownership_registry.py::build()` now returns records sorted by path,
so `runtime/generated_artifacts` (which compares parsed structures) agrees with the CLI writer.
A throwaway diagnostic script was created under `docs/repair/` during investigation and deleted; it is
not part of the repo.

Batch 3 verification (structural set: clone isolation, structural integrity, generated artifacts,
config/registry, ownership source independence): **37 passed, 2 failed in 19m31s**
(`evidence/resume4-structural-green-check.log`).

Both failures are the SAME single intentional gate, not new defects:
- `test_structural_integrity.py:142` -> `markers: incomplete marker audit failed: [] unreviewed=3`
- `test_structural_integrity.py:158` -> `assert all(item["passed"] for item in audit_items)` — fails
  only because `markers` is inside that set.

`markers` is a deliberately-red review gate: it stays red until the 3 unreviewed incomplete findings are
actually repaired. It must NOT be satisfied by editing `registry/incomplete_finding_reviews.json`
without doing the underlying work, and the allow-list in `runtime/structural_integrity.py` must not be
extended to hide it. That would be the forbidden "loosen the gate to get green".

Net position of the structural subsystem: 14/15 categories PASS, 21/21 generated-artifact checks OK,
0 unreviewed duplicate-logic groups. Blocked on 3 real findings + the succession acceptance gap.

## Session 4 — batch 5: reconciliation conflict table (2026-10-25)

G01 CLOSED at generator level. The other three ownership generators were audited and are clean:
`runtime/effect_surface.discover_effect_surfaces()`, the python-surface certifier and the
dependency certifier all derive from source and only *compare* against their registries — no
self-referential fallback. `build_contract_ownership_registry.py` was the only offender.

Contracts: rollout has 214, bootstrap 184, **bootstrap-only = 0** (clean subset relation), 30 to port
(`evidence/resume4-contracts-missing-from-bootstrap.txt`).

Conflict table built (`evidence/resume4-conflict-table.json`, sizes in
`evidence/resume4-conflict-sizes.json`):
- 368 source paths exist only in rollout -> decision PORT, no conflict.
- **618 shared paths differ** = 667,426 changed lines: 304 trivial (<10), 128 medium (10-40),
  **186 large (>40)**.
- The large deltas are mostly generated data (`docs/architecture/data/*.json`, up to 330k lines) and
  registries, which will be regenerated rather than ported. Real hand-written large conflicts to
  review include `runtime/agent_runtime.py` (+698/-19), `pyproject.toml` (~2.3k), and
  `px/py_cert/scripts/run_release_{candidate,stage_owner}.py`.

This is NOT a mechanical checkout. Porting rollout over bootstrap would discard bootstrap-side work
(the succession port, the secure-publish work, the reconciler/unit-level repairs) and would be a
silent merge — explicitly forbidden. Bootstrap remains the authoritative checkout until each conflict
is resolved on semantic grounds.

## Session 4 — batch 4: external export verification (2026-10-25)

User asked to verify that `C:\Users\Ben\Music\Pacify-X-main` had been properly diffed before going deeper
into certification. Finding: it is a **loose non-Git export and a snapshot of the rollout worktree**, not
an upstream authority (57,490 files, no `.git`, sampled source byte-identical to rollout). Full report:
`bootstrap_project\PACIFY_X_MAIN_DIR_VERIFICATION_2026-10-25.md`; survey JSON: `pacifyx_threeway.json`.

Measured gap **[OBSERVED]**:
- bootstrap `contracts/**/*.json` = **184**; rollout = **214**; export = **214**.
- 30 product contracts (cancellation-scope, gremlin-containment-proof, gremlin-host-configuration,
  gremlin-recovery-*, isolated-agent-sandbox, execution-context, dependency-identity, 11 model-routing)
  exist in rollout+export and are **absent from bootstrap**.
- Those families are exactly G02 (secure atomic writes) and G03 (sandbox/Gremlin). They are *pending
  reconciliation*, not lost.

Important correction to earlier claims in this log: "contract corpus valid, 184/184 owned" and
"21/21 generated-artifact checks OK" are true **only for bootstrap's 184-contract tree**. They cannot
detect the 30 missing contracts because the generator derives from whatever is on disk. **Bootstrap must
not be certified as the release revision until reconciliation lands.**

Nothing was copied from the export. A tree with no history cannot be cited as provenance and copying
from it would pre-empt the canonical-source decision.

Commit `3df5e53e` (batch 3) is in place on `codex/repair-reconcile-20261025`.

## Session 5 — 2026-10-25: reconciliation under Option C (bootstrap = provisional canonical target)

### Snapshot (before any port)
`.audit-handoff/20261025-reconcile/`: status/diff/log for bootstrap and rollout,
`untracked-bootstrap.tar` (72/72 members verified readable). Export `Pacify-X-main` is measured
reference only — no `.git`, so it can never supply provenance. Nothing in it was copied.

### Dependency closure (this is why "new files" could not be bulk-copied)
`evidence/resume5-port-closure.json` + `evidence/resume5-closure-graph.json` **[OBSERVED]**:
- 368 rollout-only source paths; 217 are Python.
- **96 of 217 Python files import something bootstrap does not have.** Bulk copy would have produced
  96 modules that fail at import; the contracts would have validated against an absent runtime.
- Component groups: contracts 31, redis 27, cli 25, research 24, canary 21, scripts 18, semantic 15,
  agents 12, gremlin 12, model-routing 11, tests 9, runtime-other 7.

### Batch 1 — G03 Gremlin / sandbox contracts + package  **[DONE]**
Ported 36 files (12 contracts + 24 `runtime/gremlin/*`), every SHA-256 verified against rollout
(`evidence/resume5-port-g03.json`).

One genuine semantic conflict resolved on evidence, not size/mtime:
- `runtime/gremlin/host_enforcement_backend.py` (bootstrap 4,600 B -> rollout 8,325 B). Reviewed both:
  rollout is a strict superset. It **retains** bootstrap's partial-freeze `failed_pids`/`expected_pids`
  evidence and **adds** `_suspend_pid(pid, *, job_handle)` with job-handle-scoped suspension,
  member verification, and a post-suspend inventory comparison (`set(remaining) == set(pids)`).
  Every line removed was replaced by a strengthened check. No bootstrap-only content was lost.

Tests: `evidence/resume5-g03-tests.log` -> **7 passed** (`-k "gremlin or containment or sandbox"`).
The inherited `tests/test_gremlin_regression.py` (PX-AUD-003/004) initially failed **because its mocks
used the old one-argument `_suspend_pid` signature and passed pid 999/0, which the real backend
correctly rejects**. Assertions were **not** weakened: only the patch signature and fixture pids were
corrected to match the audited API (pid must be a Job member: line 161).

Contracts: 196 valid Draft 2020-12 schemas, 0 invalid (was 184). +12 = matches rollout's 214 after the
remaining 18 model-routing/semantic contracts land in their batches.

NOT yet done for this batch: ownership/generated registries deliberately **not** regenerated — G02
(secure publication) and the remaining contract groups must reconcile first, per instruction 4.
### Batch 2 — G02 secure publication / filesystem containment  **[DONE: 32/32]**
`evidence/resume5-port-g02.json` (27 files, every SHA-256 verified), `evidence/resume5-g02-tests.log`
-> **32 passed**.

Two discrepancies from my previous report, both now resolved with evidence:
1. "secure_publish never existed in bootstrap" was **wrong** — it existed as an *untracked* file. The
   `overwrote_existing` flag in my port tool means "was present", not "was tracked and clobbered". No
   tracked file was overwritten; `git status` still shows them as `??`.
2. The 11 `record_tool_intake` failures were **not** a fixture or guard problem. Rollout's
   `tool_intake.py` is 38/-23 different: it is the interrupted **I-item fix** (single WAL transaction,
   `FileLock`, recovery, history verification). Bootstrap's guard was correct; bootstrap simply did not
   have the repaired owner yet. Ported -> tests pass with bootstrap's commissioning guard intact.
   **No control was relaxed.**

Three classes of hidden dependency were found only because the tests failed, not because the tooling
predicted them. Each is now a permanent check:
- **File-level closure** (`True-Closure.py`): 96 of 217 rollout-only modules import something bootstrap lacks.
- **Symbol-level drift** (`True-Closure.py --symbol_drift`): a module exists in *both* trees but no longer
  exports an imported symbol. Caught `bounded_walk._is_junction`, `vscode_model_bridge.set_sandbox_mode`.
- **Lazy / relative imports** (`Deep-Deps.py`): imports inside function bodies escaped `ast.walk` at module
  scope. Caught 5 more modules (`isolated_sandbox`, `execution_context`, `chat_context`,
  `prepared_group_transport`, `remote_model_bridge`). A file-level or module-level scan would have shipped
  5 modules that fail only when the code path is exercised.

All G02 ports were reviewed as supersets: `bounded_walk.py` only adds `_is_junction` (reparse-tag fallback)
and replaces three inline lambdas; `nsai_knowledge.py` replaces hand-rolled temp writes with
`atomic_write_bytes`; `vscode_model_bridge.py` adds `set_sandbox_mode`. No bootstrap-only behaviour removed.

Registries still deliberately NOT regenerated (instruction 4: reconcile source dependencies first).


## Resume6 native integration checkpoint (2026-10-25 local)

Native maxLength/UUID admission and fixture generation repaired without weakening schemas or refreshing registries. Newly exercised imports exposed absent Job custody and event-ledger locked append owners; reconciled the reviewed source implementations, preserving bootstrap namespace and stronger orphan-history reporting. Ported missing dependency-context projection only, preserving existing event consumer work. Native schema examples:196 passing subtests; integration4:121passed/1failed (remaining schema dedicated-test mappings). Earlier failed attempts retained.

Actual Windows operational probe passed after explicitly accounting for already-issued file I/O:68 Job members/67 live heartbeat children, exact retained handle custody, outside-Job PID rejected, all67 heartbeat files stable across two windows after200ms settling, native termination verified empty and supervisor tree_closed with no retained process custody. Not a network/sandbox/installed-product certificate. Source hashes and owned retained workspace/ledger/receipt in evidence/resume6-native-job-operating-proof.json; attempts1/2 preserve failed probe diagnostics. Further event/resource/process neighboring tests running. No reviewed card closure, registry refresh, package, install, certification, commit or push yet.


### Resume6 native final checkpoint

139 focused tests +196 native corpus subtests pass (evidence/resume6-native-final.log); signed workflow tests5pass; secure publisher focused suite32pass (within persistence-resume diagnostic33pass/5fixtureerrors, then corrected signed fixture5pass). Native custody neighbors64pass/1concurrency timeout under overlap; isolated concurrency+digest3pass. Keep both, do not call the combined suite green. New mandatory secure-persistence/native-runtime-integration/host-containment/native-job-operating sections defined; native-runtime-integration governed command blocks at historicalinstalled_operational before execution (evidence/resume6-governed-native-runtime.log). No gate bypass.

Current marker diagnosis is17unreviewed, not stale3:10protocol ellipsis signatures, typed exceptions/expected control flow and actual containment invariant failure need owner disposition/behavior proof; no review registry edited. Details evidence/resume6-marker-diagnosis.json. ROLLOUT_COMPLETION_PLAN.md now binds all11repair groups, standalone additional kit and ordered Day1/certification steps. AUD003/004 receive additive actual-host receipts; reviewed_closed remains0.

## Resume7 — 2026-10-26 (R04 event custody: interrupted batch work completed and re-verified)

Trust anchor re-established from Git: bootstrap `codex/repair-reconcile-20261025` @ `3df5e53e`, 41 modified + 127 untracked (the resume6 edit group is **uncommitted working-tree state**, not a commit). Rollout worktree `codex/rollout-day1-20261024` @ `5ebc7368` untouched this session. No reset/clean/checkout/overwrite was performed.

| Gate | Command | Result | Evidence |
|---|---|
| Event integrity + batch (current source) | `pytest tests/test_event_integrity_audit.py -q` | **28 passed** | `evidence/resume7-batch-failure-injection.log` |
| Operational bus suite | `pytest tests/test_operational_event_bus.py -q` | **13 passed** | `evidence/resume7-operational-event-bus.log` |
| RED-before control (same suite, legacy one-at-a-time `publish_batch` from HEAD `ed119411`) | monkeypatched legacy method, same tests | **17 failed / 11 passed** — proves the new tests detect the non-atomic publisher | `evidence/resume7-batch-red-before-legacy.log` |
| Event ledger + bus + integrity combined | `pytest tests/test_event_ledger_regression.py tests/test_event_integrity_audit.py tests/test_operational_event_bus.py -q` ×3 | **47 passed** each run (12.9–14.6 s) | this log |
| Event ledger integrity (incl. `test_concurrent_event_append_preserves_chain`) | `pytest tests/test_event_ledger_integrity.py -q` | **8 passed** (.09 s); 20/20 standalone stress iterations of the same 16-append/4-thread case passed | this log |
| Secure publisher after fixture reconciliation | `pytest tests/test_secure_publish.py -q` | **32 passed** | this log |

What changed (all in the working tree, uncommitted):
- `tests/test_event_integrity_audit.py`: added `test_batch_failure_at_every_publication_point_keeps_one_custody_image` (14 injection points across intent → journal → manifest → each of 9 target publishes → committed journal, asserting the injected boundary was the *exact* one reached and that recovery yields either zero events or the complete batch) and `test_concurrent_batch_and_single_publish_keep_one_chain` (4 concurrent 2-event batches on top of revision 1 → revisions 2..9 with a valid chain, no forked ancestry).
- `tests/test_secure_publish.py`: the `tool`/`tool-state` fixture still wrote its lifecycle state into the **old** `.agentic_engineering_os_px` namespace after `runtime/tool_intake.py` was rebound to the commission-owned `.engineering-bootstrap` namespace, so the writer refused before publication and the two cases failed for a fixture reason, not a containment reason. Fixture now seeds the namespace the owner actually reads; staging assertions now cover the owner's own staging pattern inside the WAL journal. Behaviour under test (attacker-planted hardlink never opened, failed replace preserves the prior image) is unchanged and still green.

Classification of the long-standing "105-row ledger" entries created by this session's evidence:
- PX-AUD-084 (event_id overwrite) → `TARGETED_TESTED` (3 dedicated tests + batch duplicate rejection). Not closed: no independent review.
- R04 batch atomicity / tool-intake record+state transaction → `TARGETED_TESTED` only. No operating (installed) evidence; no governed section receipt for the frozen revision.
- PX-AUD-003 / PX-AUD-004 keep `TESTED_COMPONENT_AND_NATIVE_HOST` (resume6 68-member probe is one host path, not sandbox/network certification).

Still-open, explicitly NOT claimed:
- The resume6 "5-second lock timeout under concurrent load" did not reproduce in 3 combined runs, 1 isolated run and 20/20 stress iterations; the resume6 failing process (pid 25024 in `evidence/resume6-custody-neighbors.log`) is not the current process, so the cause cannot be re-read. Disposition: `UNRESOLVED_NOT_REPRODUCED` — the event ledgers themselves are uncontended per-test fixtures, so real contention must be rechecked under installed/multi-process load before any closure.
- `test_tool_intake.py::test_record_is_versioned_and_advances_lifecycle_without_admitting_tools` still fails: the environment-discovery stage is blocked by source-authority contract ownership (`validate_registry` reports new `contracts/*.schema.json` files "missing explicit ownership record"), so `lifecycle_status()["next_stage"]` is `environment-discovery`, not `architecture-and-planning`. Root cause is G01/R01 generated-artifact reconciliation (deferred until repair freeze by policy) — the test is not edited to pass.
- `tests/test_contract_ownership_registry_source.py::test_build_needs_no_published_registry` fails on 184 vs 196 records: committed `registry/contract_ownership.json` is stale for the 12 newly added contracts. Deliberately not regenerated (source changes are still in flight); this will be repaired at the single post-freeze regeneration.
- `tests/test_test_profiles.py` (3 failures) reports "test group membership is stale" plus "section Python command must use the governed pytest module": generated test-group projections must be rebuilt by the canonical builders **after** freeze, not hand-edited.
- Governed `native-runtime-integration` section still blocks at the historical September `installed_operational` campaign state; no successor activation was attempted this session.

## Resume7 batch 3 — certification environment rebuilt; card verification (2026-10-26)

| Item | Command / check | Result | Evidence |
|---|---|---|---|
| Signed successor activation feasibility | searched registry/contracts/docs/.px for owner key material | **BLOCKED, correctly**: `validate_owner_policy` requires an ssh-ed25519 owner public key + matching `SHA256:` fingerprint; only schema *definitions* of that shape exist, no owner policy or private key on this machine, and `missing_owner_policy_authority()` deliberately raises. Not fabricable. | `runtime/project_revision_succession.py:74-141,743-747` |
| Supported interpreter | `py -0` | only CPython **3.14t** (free-threaded) is installed — a material fact for any pin claiming a supported-toolchain basis | this log |
| `.venv-certify` rebuild | renamed broken env to `.venv-certify-broken-backup`; `py -3.14 -m venv .venv-certify`; `pip install --require-hashes -r requirements-release.txt` | **rebuilt and installing cleanly** (pytest 9.1.1, PyYAML 6.0.3 hash-verified) | this log |
| Release-lock defect found + fixed | `requirements-release.txt` omitted `jsonschema` (declared only in the `test` extra) although `runtime/contracts.py` imports it | clean-room env could not even collect the suite; appended `jsonschema==4.26.0`, `jsonschema-specifications==2025.9.1`, `referencing==0.37.0`, `attrs==26.1.0`, `rpds-py==2026.9.1` with **authenticated PyPI digests for all published files** (retrieved from the PyPI JSON API, not invented) | `requirements-release.txt`; temp script provenance |
| Clean-room verification | `.venv-certify\Scripts\python.exe -m pytest tests/test_project_revision_succession.py tests/test_contract_runtime.py -q` | **66 passed, 409 subtests passed** — a clean pinned env that previously failed at import now runs | `evidence/resume7-certify-env.log`, this log |
| Card PX-AUD-005 re-verified | every `registry/engine_identity.json` record checked against disk | **6055/6055 records resolve**; 0 missing → finding resolved on current source | this log |
| Card PX-AUD-006 re-verified | `runtime.provider_gateway.scan_direct_provider_routes` | `valid True, violation_count 0, index_used True` → resolved on current source | this log |
| Succession suite | `pytest tests/test_project_revision_succession.py tests/test_revision_activation_e2e.py` | green | `evidence/resume7-succession.log` |

Environment honesty note: the only installed interpreter is the **free-threaded 3.14t** build. A certification claim that depends on the GIL build must be re-established on a standard CPython; that is recorded as an environment-dependent prerequisite, not waved through.


## Resume8 started (2026-10-26)

User resumes all remaining work from HANDOFF_RESUME8_2026-10-26.md. HEAD3df5e53e; inherited dirty source protected in .audit-handoff/20261026-resume8 (verified ZIP and SHA manifest). Expired36203 superseded; checkpoint36205/admission36206 guard read/write/execute passed. No generated refresh, broad profile, package, install or network under this repair session. Handoff claims are inherited until current owner evidence is checked. Full intake remains open; freeze is not the next step while92cards remainOPEN. Existing commit authorization persists, distinct from repair freeze. Native operating wrapper and certification preflight need scrutiny before trusting inherited green summaries.


### Resume8 segment1 ? actual proof and UI events

Native operating wrapper RED:2false-success cases accepted empty/label-only JSON. Repaired by direct native owner invocation inside governed process, strict retained proof/source/custody assertions, no unregistered intermediate child, unsupported required host fails instead of skip, unique proof file in registered retained workspace; historical resume6 evidence no longer overwritten.5tests pass including actual68-process WindowsJob operation (resume8-native-proof.log). The retained settling observation is preserved.

UI event RED:5of5causal checks fail. Narrow semantic port repairs bounded cumulative buffering, post-validation sequence, immutable copied canonical event, independent sync/async observer delivery and nested live/snapshot secret redaction; preserves old controller/worker/catalog interfaces.27Nodecausal+neighbors pass,0skipped. AUD044/045tested integration only; no installed-host/review closure.

New mandatory event-integrity and ui-event-integrity gates wired with actual files; native proof includes rejection tests in mandatory topology and coverage constants. Governed native/UI runs correctly blocked by historicalinstalled_operational state. Current certification preflight FALSE:11missing memberships/4missing files before this segment; source reconciliation remains substantial. New Git inventory excludes .git pointer and custody; raw unbounded run retained and bounded inventory separately records5large artifacts for explicit review. No source files copied by inventory. No fresh registry hashes, package/install, fullprofile, commit, push or certification.


### Resume8 segment2 ? local commit and additional native proofs

Current HEAD 7b25e2e8bc9bef6e99fe5a1aa77c6f99f2b49368 (7b25e2e):11explicit JS source/regression paths committed; local commit is a reversible repair checkpoint, not intake closure/freeze. Existing user authorization to commit/push persists; the handoff's agent-imposed wait-for-freeze does not override it. No push yet. Inherited dirty work remains protected.

Task state/registration RED8fail plus controller RED3fail reproduced. Fixed memory publication on synchronous failure, serialized asynchronous writes/latched failure, corrupt-load refusal, immutable identities/terminal states, one live run, stale worker disposable and async-health fencing. Native controller waits for durable selection before dispatch, rejects task/run mismatch, retains usage before abort and drops late events.32Node causal/neighbors pass; AUD039/041/042/043/065 tested integration only. Snapshot API still1.0; generation/evidence/mesh integration remains open.

Secure persistence35pass includes actual Windows sharing-lock retry/permanent denial and registered owned crash_writer os._exit(23) after partial fsync; old committed target survives, uncommitted prepared image retained unchanged through fresh publication. New required secure operating test wired. Preflight5false-coverage bypasses reproduced and fixed (option/plugin/collection environment);18focused negatives pass, actual-repository prerequisite test remains unsatisfied and must stay visible.

Budget guards narrowly merged from newer source while retaining bootstrap resource validation and iterative DAG:41neighbors pass,18billing checks include a real native receipt crossing to registered Node verifier with tamper/wrong-owner negatives and closed process custody. Gateway refuses4previously accepted truthy fake receipts;21Node neighbors pass. Reservation/durable settlement pipeline is not yet ported or claimed complete.

All segment details/source hashes: evidence/resume8-segment2.json. New required agent-task-lifecycle, billing-budget, provider-settlement-contract sections wired; campaign phase still prevents governed execution. No generated refresh/full-profile/package/install/network/certification. reviewed_closed remains0.


### Resume8 user stop / Resume9 handoff (2026-10-26)

User explicitly stopped implementation. Current authoritative bootstrap HEAD7b25e2e8bc9bef6e99fe5a1aa77c6f99f2b49368 is local only; dirty/untracked work retained. Updated handoff: docs/repair/HANDOFF_RESUME9_2026-10-26.md. No further repairs/tests run after stop. No Python/Node/Git processes observed at stop. Mandatory coverage remains false, governed phase blocked, reviewed_closed0; not certified or pushed. Fresh admission required on resume.
### Resume9 segment 1 — event-bus lock deadlock (2026-10-26)

Fresh admission obtained (checkpoint `…36208`, admission `…36209`); read/write/execute guarded. Snapshot of inherited dirty state at `.audit-handoff/20261026-resume9-*`; no inherited edits reverted. HEAD still `3df5e53e`.

REPRODUCED_THIS_SESSION: `test_concurrent_batch_and_single_publish_keep_one_chain` failed with `FileLockTimeout` (5s) on 2 of 3 runs; `tests/test_file_lock_contention.py` hung. Causes: (1) Windows `msvcrt.locking` regions belong to the **process**, so a sibling thread's byte-range attempt competes with a region its own process already holds, and the on-disk lease cannot arbitrate between threads that all started concurrently; (2) `_heartbeat_once` held the non-reentrant `_metadata_guard` and then re-entered it via `_write_record` — a deterministic self-deadlock. Fix: process-local per-file-identity exclusion claimed before any byte-range attempt, released after, with a level-triggered `notify_all()` handoff (a single notify can be consumed by an already-expiring contender); timeout path releases only the in-process slot; `_metadata_guard` re-entrant with `_write_record` as the single locked primitive; heartbeat thread explicitly daemon. Cross-process lock and lease semantics unchanged.

Evidence: `evidence/resume9-lock-red-before.log`, `evidence/resume9-lock-residual-red.log` (second distinct failure retained), `evidence/resume9-lock-timing-probe.py`, `evidence/resume9-file-lock-suite.log` (10 pass), `evidence/resume9-event-full.log` (42 pass; the same pair was 1 failed under inherited source). `REPRODUCED_THIS_SESSION` — also: contract corpus round-trip 195 schemas / 0 failures (`evidence/resume9-contract-roundtrip.py|.log`), covering PX-AUD-008/009/010 classes; billing budget audit, secure-publish operating, native-job probe/verdict and the three present required Node suites pass.

Blocking finding, not closed: `validate_certification_pipeline` is false for 4 reasons — `tests/test_rollout_inventory.py` and `extension/tests/billing-settlement-audit.test.js` were never ported (they need `scripts/rollout/*` and `src/agentHarness/durableTaskState.js`, absent here), and `tests/test_host_enforcement_audit.py` / `tests/test_secure_publish_operating.py` exist but are not in `REQUIRED_PYTHON_TESTS`. No membership edited to fake coverage. `provider_route_scan` reports `index_stale` against this checkout's dirty `runtime/contracts.py` and `runtime/file_lock.py`; regeneration stays deferred to post-freeze canonical order. No commit/push/package/install/network/certification. `reviewed_closed` remains 0.

### Resume9 segment 1b — status ledger sync + ownership correction (2026-10-26)

Ownership: HEAD advanced to `7b25e2e8` (previous owner's "user requested stop and handoff" commit) while this segment ran. This segment made no commits and performed no reset/clean/replace; the lock repair was verified on `7b25e2e8` plus inherited uncommitted edits. Re-verified that `tests/test_rollout_inventory.py` and `extension/tests/billing-settlement-audit.test.js` are still absent and still reported as `missing_membership`.

`docs/repair/REPAIR_STATUS.json` regenerated from the authoritative kit queue (it previously held only a five-card hand-maintained subset, leaving 100 findings without any disposition). Result: 105 unique cards; kit states `UNVERIFIED_CURRENT_REPO 54`, `TESTED_INTEGRATION 41`, `IMPLEMENTED_UNVERIFIED 10`; all reviewers `UNASSIGNED`; `reviewed_closed 0`; zero cards `closed`; the five previously hand-listed cards now carry their real kit state (`005/006/007` resourceless `UNVERIFIED_CURRENT_REPO`, `084/085` `TESTED_INTEGRATION`) with prior evidence text retained and explicitly marked as inherited, not re-verified. Pre-sync copy: `.audit-handoff/20261026-resume9-REPAIR_STATUS.pre-sync.json`. Generator refuses unmapped kit states.


## Resume10 started (2026-10-26)

Fresh checkpoint36213/admission36214; read/write/execute guards passed. Canonical HEAD7b25e2e8 actual message Fix agent task persistence and event observer custody; prior handoff attribution corrected. No visible Python/Node/Git writers at kickoff. Inherited dirty/untracked bytes protected and ZIP verified in .audit-handoff/20261026-resume10 (existing audit backups retained in place). First segment audits file-lock waiter retirement/identity and bounded causal tests; intake open, no speculative generated refresh/package/install/certification.


### Resume10 segment1 - lock lifecycle verified

Inherited lock repair had4causal failures: waiter retirement split, first-creation path/identity mismatch, same-instance reentry ownership loss, heartbeat startup leakage. Fixed reference-counted registry with pinned open-file identity, owner-specific release, failure cleanup and acquired-byte tracking.65focused lock/event neighbors pass with closed supervised custody (resume10-lock-neighbors.json). New hostile lifecycle suite included in mandatory event section/preflight. Governed event run remains phase-blocked, not passed.105unique cards independently checked;0closed. Source hashes/limits in evidence/resume10-segment1.json. Next: missing rollout inventory/durable billing owners; intake remains open.


### Resume10 segment2 - durable async billing integration

Ported/reviewed ledger semantics with actual asynchronous VSCode workspaceState acknowledgment, task/run/invocation ownership and pending/settled cumulative ceilings. Native invoker now carries reserved invocationID. Typed receipt settlement/dedup, canceled-return usage persistence, legacy untracked-spend denial and unknown-charge holds verified:51Node checks;27Python native-gateway neighbors. Added real billing-settlement required suite/section, not filesystem helper stubs. Governed billing remains phase-blocked. Details/source hashes/remaining cross-host CAS, failed-outcome reconciliation and native estimate requirements: evidence/resume10-segment2.json. No live-provider/install/certification or card closure claim.


### Resume10 segment3 - source intake and real mandatory coverage

Added actual source inventory/review-bound integration owners instead of unsafe bulk copier. Pinned bounded physical reads reject reparse/hardlinks; no missing-parent write effects. Reviewed per-file apply retains preimages/partial-failure journal and never deletes or overlays generated state.79source/secure/preflight tests pass incl actual Windows paths;94release-owner tests pass. All29mandatory suite memberships/files now present;21required section definitions. This is structural coverage, not current governed receipts/certification. Governed inventory blocked by historical phase. Contract214denominator fully inventoried:188exact+2JSONequal+3retain stronger/canonical;21stillneed dependency integration. Reference210ownership rows miss4succession contracts. See evidence/resume10-segment3.json for limitations. No source bulk port, generated refresh, package/install/certificate or finding closure.


### Resume10 segment4 - restart/cancel/stream custody

Three causal task defects repaired: mutable policy references, redispatch after worker-selected restart with unknown effects, unbounded interrupt promise. Returned records frozen; uncertain restart failclosed; bounded cancel request retains active fencing until real settlement. Four streaming custody failures reproduced and repaired with actual ReadableStream cancellation/release on malformed frames and abort.50combinedneighbors pass, no skips. Agent-task/provider-stream/secure governed attempts all phaseblocked. Added actual streaming suite to mandatory coverage. Full recovery/mesh/generation and per-execution native interrupt proof remain open; no closure. Hashes and red/green process receipts: evidence/resume10-segment4.json.


### Resume10 segment5 - native protocol truth and context provenance

14native protocol causal failures reproduced;57protocol/gateway/budget checks pass. Explicit unsuccessful Responses status produces error, never success finish; actual gateway lifecycle failed with conservative reservation-burn receipt. SSE incremental UTF8 and LF/CR/CRLF work across every tested cut; whitespace output retained; Anthropic max_tokens/tool_use map to length/tool_calls. Five context causal failures reproduced;55combined Node checks pass. Exact content digest and metadata/instruction-inclusive budget enforced; real message consumers keep retrieval in user-role context. An accidental cp1252 Unicode conversion introduced during this session was identified by an unchanged neighbor and reverted to original source bytes; failed attempts retained. Remaining: live-model adversarial response and credentialed route acceptance unavailable; conservative failure burn remains explicit; no claim of actual paid failure reconciliation; namespace adjudication corrected:188exact+2JSONequal+1stronger authorization retained;2namespace paths require migration/caller review and21dependency reviews at that checkpoint; no schema rewrite merely to match reference. Evidence/source hashes: docs/repair/evidence/resume10-segment5.json. No independent finding closure or release certification.


### Resume10 segment6 - preflight and actual owner startup enforcement

9startup/collection bypass causal failures reproduced. Actual test owner now refuses collection/startup overrides before workspace/child creation; native exact engine-root PYTHONPATH remains supported for legitimate workflow/owner imports, foreign/appended paths denied. Mandatory Node commands deny import/require hooks and filters. Config environment cannot override collection. 133preflight/release/process-owner checks pass including actual Windows abrupt owner-death Job cleanup; initial overbroad engine-root rejection corrected without weakening the existing drill. Remaining: all governed section receipts remain blocked by historical campaign phase; structural coverage is not execution, installed acceptance or certification. Evidence/source hashes: docs/repair/evidence/resume10-segment6.json. No independent finding closure or release certification.


### Resume10 segment7 - remote catalog dependency and asset closure

Real catalog import failed from2missing owners; four reviewed candidate files ported plus current consumer/schema/package declarations. Native signed profile integrity, public address pins, exact service identity and conservative unavailable catalog verified;6functional checks passed before added source-ownership check. Combined remote/schema/preflight run:76passed,411subtests passed,1expected stale published ownership assertion failed (published196 vssource197). No generated registry refresh during open intake. Schema uses current framework asset resolver in both source and simulated installed layout. This is not a package/install run. Remaining: full prepared remote group effect owners remain missing; no chat/transport commissioning or live credentials; Gemini protocol remains unsupported by the current native surface owner; no false ready claim from a mapping row; source-derived197ownership map remains unpublished until legitimate freeze/reconciliation; canonical namespace and distribution migration remain separate caller/packaging work. Evidence/source hashes: docs/repair/evidence/resume10-segment7.json. No independent finding closure or release certification.


### Resume10 segment8 - final failure and operating custody

Two additional exception leaks reproduced/repaired;68lock/event neighbors pass, incl fstat/close failure and unsettled heartbeat retaining lease until real stop. Final8native Job/verdict/Windows reader-lock/crash checks pass with process trees closed.25required sections resolve,33required suites structurally covered; governed receipts still phaseblocked. Exact original process/probe proof copies in evidence/resume10-custody with SHA manifest; no private fixture keys copied. Script parent directory registration timing gap disclosed in resume10-script-custody.json; no retroactive creation claim. Currentcontract denominator197; candidate214adjudication now188exact+2JSONequal+1stronger targetauth+1component port,20dependency reviews+2namespace migration reviews stillpending. Earlier3-retain namespace assertion superseded. No card closure or certification.


### Resume10 segment9 - production gateway identity and client protocol

Actual extension registration now resolves worker provider/model digest and output bounds from native catalog; stale, absent, ambiguous or unavailable profiles disable dispatch. Static display labels are not authority. Native AbortSignal is adapted to cancellation token; trailing and newline JSONL share strict terminal receipt handling; asynchronous consumer failures reject the operation. 51 gateway/billing/context/task/native-bridge checks passed; 29 certification-preflight checks passed. All supervised trees closed. Actual native list returned models empty, authority_granted false and remote unconfigured. No admitted model means live agent inference acceptance is unavailable. 26 mandatory section definitions and 35 required suite paths; governed agent-gateway attempt phaseblocked (historical installed_operational). Native JS child process registration/Job custody and fully bounded cancel closure remain incomplete; controlled child framing tests do not certify real process containment. Evidence: docs/repair/evidence/resume10-segment9.json. No finding closure, push, install or certification.
