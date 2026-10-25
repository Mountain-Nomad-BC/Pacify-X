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
