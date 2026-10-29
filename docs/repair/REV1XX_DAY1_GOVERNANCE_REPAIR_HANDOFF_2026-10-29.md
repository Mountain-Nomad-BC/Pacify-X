# Rev1.xx Day1 governance repair continuation — 2026-10-29

Supersedes the work-state portion of `REV1XX_DAY1_RESUME_HANDOFF_2026-10-29.md`; retain both predecessors for campaign/custody history. This is a repair checkpoint, not release acceptance.

## Campaign and authority

The existing signed Day1 successor is already active. Do not replay activation or invent another authorization. Project `prj_pacify_x_rev1xx_day1_20261029`, campaign `pacify-x-rev1xx-day1-20261029`, phase repair, intake open, unresolved 112; independently reviewed closures remain 0/105. No generated projection refresh, full profile, broad validation, package, installation, network publication or certification occurred here.

Active gap is PX-OS-1067. This continuation used checkpoint `gap-event:PX-OPERATIONAL-GAPS-20260816:000000036306` and session admission `...000000036307`, `project-day1-governance-external-fixtures`. Exact read/write roots: repository and `C:/Users/Ben/AppData/Local/Temp/Pacify-X-day1-owned`. Read, write and execute guards passed individually. Admission evidence: `evidence/day1-governance-external-temp-admission.json`. A final checkpoint/session closure is retained in `evidence/day1-governance-repair-final-checkpoint.json`; obtain fresh admission before subsequent work.

## Repairs in this continuation

- `runtime/source_boundary.py`: bounded authored traversal prunes excluded custody before touching its children, rejects authored links, and treats the root `.audit-handoff` recovery directory as runtime custody. A same-named nested source directory remains authored. Excluded retained/broken test links no longer poison an authored inventory.
- `scripts/clean_source_export.py`: nested source without its own Git root cannot claim its ancestor repository's commit or worktree identity.
- `runtime/event_ledger.py`: recovery intent completion retains the exact original bytes in a unique history file alongside canonical history, instead of unlinking the original. Tests cover both existing and new canonical history and noncanonical whitespace.
- CLI lock tests assert the actual timeout/blocked-operation contract, allowing the native same-process thread-lock wording. The key-isolation fixture checks a fresh authority root inside the registered process workspace and rejects inherited authority. The required-section assertion includes all 29 existing mandatory sections.

No test membership, assertion on acceptance of current projections, containment policy or time budget was removed to obtain a pass.

## Verification

All final helpers report `tree_closed=true`, `resource_inactive=true`. Native section managed basetemps were reclaimed through the resource owner. Retention-required outer workspaces remain registered; do not delete them casually.

| Run / evidence basename (under `evidence/`) | Result |
|---|---|
| `resume10-day1-source-inventory` | Governed section: 25 passed, exit 0 |
| `resume10-day1-event-integrity` | Governed section: 118 passed across 8 chunks, exit 0, 170.625 s |
| `resume10-day1-testing-governance-repaired` | Governed section: **6 failed, 1010 passed, 1 skipped**, plus 12 passing subtests; exit 1, 695.969 s, six chunks; execution_valid=false |
| `resume10-day1-governance-source-and-fixture-check` | 11 selected checks passed |
| `resume10-day1-governance-new-regressions` | 3 new boundary/export regressions passed |
| `resume10-day1-event-intent-retention-neighbors` | 58 focused event-ledger neighbors passed |
| `resume10-day1-governance-materialization-stable` | 2 passed, 1 failed: actual manifest/test evidence disagreement below |
| `resume10-day1-governance-remaining-diagnosis` | Diagnostic process exited 0; reports invalid contract/effect state, **not a validation pass** |

Each basename has `.json` supervision proof and `.log` output. Current testing-governance failures decreased from 17 to 6. Chunks 3–6 all passed. Failed causal runs remain retained: `day1-governance-causal-fixtures`, `day1-event-intent-retention-red`, and `day1-governance-materialization-check`, each prefixed `resume10-`. The first materialization run overlapped this agent's source edits and correctly rejected changing inputs; that is an avoidable invocation mistake, not an environmental failure. The subsequent stable run proves the remaining real failure. Preserve all these distinctions.

## Six remaining failures and how to proceed

1. Two tests in `test_test_profiles.py`: `test_certification_groups_are_exhaustive_exclusive_and_bounded` and `test_group_status_is_receipt_driven_and_covers_every_test_file`. The generated group index rejects its content/parser identity. Explicit reconciliation is required; do not rebuild during open intake or disable currentness checks.
2. `test_cli_commands.py::CliCommandTests::test_startup_classification_and_working_set_commands_are_bounded`: persisted world-state detail paths still refer to the old release locator, while the current builder derives a per-campaign release identity path. Previous handoff proved fresh builder output validates. Leave the generated projection untouched until the registered reconciliation stage.
3. `test_cli_commands.py::CliCommandTests::test_contract_corpus_is_exposed_as_an_auditable_boundary`: diagnosis now proves 214 contracts versus 197 owned. Seventeen model-group, remote-provider/attachment and semantic contracts lack explicit ownership records. Their exact paths are in `resume10-day1-governance-remaining-diagnosis.log` under `contracts.errors`. Review actual enforcement owners and repair authored ownership declarations; distinguish those decisions from later generated publication. Do not merely assign arbitrary ownership or suppress count checks.
4. `test_release_artifacts.py::test_materialized_release_source_is_bounded_and_complete`: test constant `DECLARED_PACKAGED_EVIDENCE=()` claims historical package inputs were retired, but setuptools data-files still select 12 existing evidence files. Materializer correctly reports 12. Resolve intended package/reference policy against `policies/rev1xx-validation.json` and `pyproject.toml`; do not pretend these files are fresh acceptance evidence or make the test tautologically accept the materializer's own output. The external workspace correction separately fixed the other two materialization cases without relaxing source/destination containment.
5. `test_effect_surface.py::test_every_executable_effect_surface_is_owned_and_bounded`: multiple causes, not just generated registry staleness. Full diagnostic errors are retained. Specifically, `runtime/secure_publish.py:166` unlinks failed prepared images outside the reclamation owner; `scripts/inventory_repair_reconciliation.py:20` invokes Git without a timeout. Numerous mutating producers have missing/stale custody classifications; some newly discovered producers are unclassified and the certification-pipeline producer's declared effect denominator differs. Repair causal source/ownership issues first. Then reconcile generated effect/custody registries only at the authorized stage. Do not whitelist hard deletion or blindly regenerate hashes. Secure-publish failure tests currently require no prepared remnants, so redesign retention/resource ownership and adjust causal tests together, including actual Windows contention/crash tests; a bare unlink-to-rename replacement is not a complete ownership design.

## Remaining project work

Controller mesh review remains open: worker refresh/currentness, persisted restart/recovery fencing and bounded cancellation. Read-only inspection found mesh dispatch does not mirror the single-turn refresh/recovery checks and mesh interrupt awaits are unbounded. These are findings to reproduce, not completed repairs or accepted behavior. Also inspect whether mesh execution persists enough ownership for restart detection; a mock recovery check alone is insufficient.

The 105-card review, production model-group commissioning, independent host recovery verification, provider settlement, missing historical evidence and inherited dirty-tree reconciliation remain open. Do not close cards or intake on the basis of these local passes.

## Git and reproducible operation

Starting HEAD was `d8e483847d3553d783480c632ff0844647ff9c29` on main, ahead of origin/main by two. A focused local commit records only the nine repaired source/test files listed above plus this checkpoint and its explicit evidence; inspect Git log for its resulting ID. The large inherited source/evidence relocation worktree remains dirty and preserved. No push. Do not `git add -A`, reset, clean, delete backup refs, or stage keys, `.tmp` or mutable native state. Verify byte-exact evidence relocation mappings before any later broad commit.

Development interpreter remains `.venv-repair/Scripts/python.exe` (3.11.9, pytest 9.2.0), not a claim about the pinned release environment. Use native owned runners, sequentially, and hold source fixed while materialization or whole-section gates read it:

```powershell
& .\.venv-repair\Scripts\python.exe .tmp/resume10/run_governance_external.py <unique-name> --section -m runtime.cli test-section run <section>
& .\.venv-repair\Scripts\python.exe .tmp/resume10/run_governance_external.py <unique-name> -m pytest -q -p no:cacheprovider <test-path> -k <selection>
```

That local helper reads the old admission evidence, so renew it and update the helper's admission source before reuse. It allocates registered disposable workspaces under the exact admitted external temp root, derives native section budgets, supervises process trees and retains truthful evidence. `.tmp` helpers are local conveniences, not durable shipped code. `exec_command` session polling worked for the full 696-second gate in this environment; no unregistered background process is needed. If a future environment needs `Start-Process`, use `-WindowStyle Hidden` and preserve native supervision.

Canonical PX-OS-1067 next action remains exactly:

> Run the single revision/generated-projection reconciliation, make every governed section current, then execute exactly one full profile, validation, package, install, installed-system operational test, and certification in registered order.

This is a future ordered action, not authorization to skip intake/repair prerequisites. No owned test remained running when this handoff was written.
