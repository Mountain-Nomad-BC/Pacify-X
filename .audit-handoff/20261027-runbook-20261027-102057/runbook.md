# Pacify-X — Complete Repair, Integration, Operational Acceptance & Certification Runbook

**Prepared:** 2026-10-27  
**Purpose:** A durable, executable set of instructions for the next coding/verification agent to finish *all* remaining Pacify-X work without erasing existing changes, confusing test passes with product readiness, bypassing governance, or stopping at ordinary engineering problems.  
**Release status:** **NOT COMPLETE — NOT CERTIFIED — NOT CLEARED FOR PRODUCTION.**  
**Source of this checkpoint:** user-provided **Resume14 (2026-10-27)** status. All quantities and test outcomes below are **inherited reports**, not independently rerun by this document's author. Confirm them against the actual repository and retained evidence before relying on them.

> **Order of authority:** current `AGENTS.md` and canonical source/governance contracts > repository state and machine-generated evidence > active `docs/repair/SESSION_STATE.md` and execution ledger > this runbook > earlier conversation summaries. If documents disagree, record the discrepancy and resolve it from sources/tests; never silently pick the more convenient claim.

---

## 0. Non-negotiable completion contract

1. **Finish the entire authorized engineering scope, not just a test subset.** This includes the full 105-card first repair kit, reference-worktree reconciliation, model-group/T.I.E. integration, WorkflowStudio and mesh execution, namespace and succession handling, the additional repair kit (R13), installed operations, VSIX, and final certification.
2. **No blanket sign-offs.** A repaired component, green unit suite, Git commit, generated-registry count, installed wheel, and independently reviewed certificate are **different states**. Preserve those distinctions everywhere.
3. **Use the existing checkout and preserve all user edits.** No `git reset --hard`, `git clean`, `git checkout -- .`, wholesale worktree replacement, deleting receipts, editing prior protected campaigns, or hand-editing generated JSON/hash indexes. No force push.
4. **No security shortcuts.** Do not forge signers, reinterpret fixtures as real signatures, weaken signed-capability checks, suppress guards or test failures, or call a mocked network/provider/Windows host operation "operational." All distinct effects require the admission mandated by `AGENTS.md`.
5. **Continuous disk checkpoints.** After *every* bounded repair/test, update persistent logs and next-step state. Never depend on an end-of-session handoff or token-limit warning.
6. **Do not stop for routine work.** Missing premade patches, changed line numbers, test failures, merge conflicts, stale registries expected during open intake, and implementation decisions answerable from contracts/source are tasks to solve, not user blockers. Escalate only a genuinely external authorization, incompatible product choice, irreversible operation, or unavailable required operating environment.
7. **Never claim 100% success unless all required release gates pass with independently reviewable evidence.** Unavailable required gates remain explicit blockers.

### Current repository checkpoint — verify, do not assume

| Role | Value reported by Resume14 |
|---|---|
| Canonical integration checkout | `C:\Users\Ben\Documents\bootstrap_project\Pacify-X` |
| Repair branch | `codex/repair-reconcile-20261025` |
| Last reported HEAD | `9583fcd9` (local, reportedly not pushed) |
| Working tree | 16 modified + 39 untracked; mostly inherited; preserve |
| Reference rollout worktree | `C:\Users\Ben\Music\Pacify-X-rollout-20261024` @ `5ebc7368`, reportedly untouched |
| Repair ledger | `docs/repair/REPAIR_STATUS.json` — 105 cards, all `UNASSIGNED` in Resume14, `reviewed_closed: 0` |
| Last reported ledger checkpoint | suffix `…36236` (retrieve actual full ID from disk) |
| Source contract count | 203 |
| Published ownership registry | 196 (known, documented 7-contract drift) |
| Certification coverage diagnostic | expected `True / 43 / []` — verify |

**Do not mistake `UNASSIGNED` for 105 known-unrepaired components.** It means the last ledger needs card-by-card disposition populated from actual evidence. Equally, do not mass-assign `TESTED` without reviewing the work per card.

---

## 1. Initialize without harming existing work

Read the current files before editing:

- `AGENTS.md` (present according to Resume14; authoritative for governance/admissions).
- `docs/repair/SESSION_STATE.md`, `docs/repair/TRACKING_LOG.md`, `docs/repair/ROLLOUT_COMPLETION_PLAN.md`, `docs/repair/REPAIR_STATUS.json`.
- Current first-kit `tracking/ALL_105_REPAIR_QUEUE.csv`, all 105 punch cards, execution order, acceptance matrix, and `tracking/EXECUTION_LOG.jsonl` under `C:\Users\Ben\Downloads\PX_REPAIR_UNBLOCK_AND_COMPLETION_PLAN` (locate exact content; do not guess paths within it).
- The separate `C:\Users\Ben\Downloads\PacifyX_105_Findings_Complete_Repair_Kit` and its cards/evidence; do not assume it is already subsumed by the first kit.
- The last two source handoffs (particularly Resume14) and existing evidence logs under `docs/repair/evidence/`.

Run from PowerShell in the canonical checkout:

```powershell
Set-Location 'C:\Users\Ben\Documents\bootstrap_project\Pacify-X'
Get-Content AGENTS.md -Encoding UTF8
$branch = git branch --show-current
$head = git rev-parse HEAD
$state = git status --porcelain=v2 --branch
$worktrees = git worktree list --porcelain
$branch; $head; $state; $worktrees
python scripts/operational_gap_ledger.py validate
.\.venv-repair\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); from pathlib import Path; from scripts.validate_certification_pipeline import certification_coverage as c; r=c(Path('.').resolve()); print(r['valid'], r['required_count'], r['missing_files'])"
```

**Expected from previous report (not a substitute for execution):** ledger valid; coverage `True / 43 / []`; published ownership drift red pending source freeze.

1. Create a timestamped evidence snapshot *outside* disposable build/temp locations: worktree topology, HEADs/branches/remote refs, porcelain statuses, staged/unstaged **binary** patches, complete copy/tar of untracked content, SHA-256 manifests, installed tool versions and running managed processes. Verify backup completeness before mutation. Do not overwrite older snapshots.
2. Capture an immutable **pre-repair baseline** and identify which changes are owned by the user, other AI sessions, or this session. Use a separate authorized repair branch/worktree where possible; do not change source tree ownership without checking `AGENTS.md`.
3. Identify and record any existing long-running tests/processes before launching another. Preserve their logs, ensure no orphan process carries a lock, and use supervised bounded execution for fsync-heavy suites that exceed foreground tool limits.
4. Check actual Git remote state with `git ls-remote` **only under any required network admission**. A prior local tracking ref, `git push` acknowledgement, or branch label is not remote SHA proof.
5. Record all initial discrepancies in `SESSION_STATE.md` and the execution ledger, including exactly what could not be inspected.

---

## 2. Persistent evidence and reporting format

Keep these artifacts synchronized after each bounded unit of work:

| Artifact | Required purpose |
|---|---|
| `docs/repair/SESSION_STATE.md` | HEAD, branch, dirty paths, current card/owner, last successful command, current failures, live processes, **single exact next action** |
| `docs/repair/TRACKING_LOG.md` | Human-readable chronology and cumulative gate status, with explicit inherited vs observed labels |
| `docs/repair/REPAIR_STATUS.json` | Exactly 105 canonical cards, each with state, cause, files, hashes, tests, operating evidence, reviewer, and disposition |
| First kit `tracking/EXECUTION_LOG.jsonl` | Append-only machine-readable event per action/test/decision; no rewriting past records |
| `docs/repair/evidence/` | Full command/stdout/stderr/exit-code receipts, structured reproductions, screenshots/host logs when needed, manifests |
| `docs/repair/RECONCILIATION_MATRIX.csv` (create if absent) | Canonical vs rollout path, origin/HEAD, source hashes, semantic decision, dependency closure, validation |
| `docs/repair/RELEASE_ACCEPTANCE_MATRIX.csv` (create if absent) | Every required section, installed scenario, reviewer, exact revision/artifact digests, result, limitation |
| `docs/repair/BLOCKER_REGISTER.md` (create if absent) | External authority/request, why unavoidable, responsible owner, safe pending work, earliest gate affected |

**State vocabulary:** `UNASSIGNED` → `REPRODUCED` / `DIAGNOSED` → `IMPLEMENTED_UNVERIFIED` → `COMPONENT_TESTED` → `INTEGRATION_TESTED` → `OPERATING_TESTED` → `INSTALLED_TESTED` → `REVIEW_PENDING` → `REVIEWED_CLOSED`. Alternative terminal `NOT_APPLICABLE_REVIEWED`/`SUPERSEDED_REVIEWED` requires exact evidence and independent approval. Use only values allowed by the repository's actual schema; map this conceptual ladder to valid native enums, rather than inventing ledger enums that break validators.

**Per-card evidence contract:** finding ID and original requirement; affected owners/callers; before and after hashes; failing causal test or supported diagnosis; source change/commit; positive and adversarial checks; actual operating scenario and restart/failure injection if applicable; generated artifacts impacted; known limitations; independent reviewer identity and receipt; closure decision. *One broad test log must not be stamped across 105 cards as 105 reviews.*

**Checkpoint cadence:** after every patch + focused test, every failed gate, every governed operation, and before any context compaction/long-running test. At the start of any new AI session, read the latest disk checkpoint and recompute Git/ledger status before coding. A failed check remains in the record even if later passes.

---

## 3. Preserve tested work; independently evaluate its completeness

Resume14 reports these repairs/tests (verify log paths and current source first):

| Area | Reported evidence | What still must be proven before closure |
|---|---|---|
| Windows FileLock / event chain | 42 event+bus passed; 10 lock contention passed; 23 neighbouring passed; red reproductions for timeout and heartbeat self-deadlock | Process + thread contention, exact owner/release, stale lease, crash/restart, Windows host evidence, event chain durability, independent review |
| Semantic entity contract | `framework_root()` and fail-closed `SemanticEntityError`; emitted-record schema | Packaged contract accessible after clean install, publish→restart→readback, missing-schema denial, callsite compatibility |
| Contract fixture generation | 203 schemas, 0 generation failures | Native validator agrees, examples round-trip, invalid boundary cases rejected, no generated-registry concealment |
| Packaging | `contracts/semantic` and `contracts/project_revision_succession` added to package data | Inspect actual wheel/sdist contents and installed read paths; no repository import fallback |
| T.I.E. missing function | Clear `NotImplementedError`, regression for unsupported path | **Feature remains unimplemented**; never mark completed until real fuse owner/callers work |
| R02 paths | 94 focused passes | Hostile symlink/reparse/hardlink, concurrent write, crash recovery and installed use |
| R03 containment | component/host runs reportedly pass | Actual Job tree, sandbox/network/readiness/escape gates and installed host |
| R05 billing | 18 Python + 20 Node pass | Real provider usage receipts, cross-language boundary, cancellation/restart/zero-budget, attribution, installed routing |
| R06 lifecycle | reportedly passes | Live agent dispatch/pause/cancel/deadline/restart/no stale effects |
| R08 memory/NSAI | 50 pass | Owner isolation, lost/corrupt evidence, persistence across reboot, retrieval under real workload |
| R09 scheduling | reportedly passes | Worker loss, fairness, resource saturation and exact retry semantics |
| R11 model resources | reportedly passes | Real supported model process/lease, startup failures, cleanup/reclaim, no double/free leak |
| Model-group | 41 pass | Real `tie_bindings`, fusion, resource attribution and dispatch |

**Review procedure:** join the 105 punch cards to existing implementation tests and native evidence; verify current source at the reported HEAD; run missing causal and adversarial scenarios; classify *each* card honestly; record independent review separately from implementation. Do not use a single reviewer/model to self-certify a claim contrary to the project's independence requirements.

---

## 4. Complete source reconciliation and R01

1. Reconcile **all** rollout-only paths, all shared semantic conflicts, generated outputs, and source/contract ownership differences between bootstrap and `Pacify-X-rollout-20261024`. Recompute the diff against **current** HEADs; older conflict counts were time-specific and are not current denominators.
2. Preserve bootstrap as provisional canonical integration authority, not proof it contains every needed feature. Do not bulk-replace it with rollout or copy reference-only dead modules just to increase contract counts.
3. For each difference: record source hash/commit, whether generated or handwritten, real callers/entry points, import closure, policy, test coverage, release inclusion, and `PORT / MERGE / RETAIN_REFERENCE / RETIRE_WITH_REVIEW` rationale. A different file name, equivalent line count, or file existence is not operational evidence.
4. Resume14 reports **12 contract dependency reviews done**: 11 reference-only, 1 reconciled; 10 of the 11 absent runtime owners. Recheck their reachability and classify as reference-only where warranted. Do **not** blindly import unreachable schemas or mark them as missing production functionality without evidence.
5. Resolve **nine `PORTED_COMPONENT_TESTED_GENERATED_PENDING`** records. For each, demonstrate its real implementation and tests, then hold derived publication until freeze as required. Update the ledger to the strongest justified state.
6. Treat the two namespace migration records as linked architectural tasks (§7), not isolated file renames.
7. Verify all ownership/effect/dependency generator implementations derive source truth, fail on missing authoritative rule, and do not copy their own published outputs as ground truth. Validate manifests and Python/Node/VSIX install surfaces.

**R01 exit:** every meaningful source difference and executable owner has a decision; no missing real caller, unsupported active contract, or unexamined package manifest; all generated records have canonical source and agreed timing.

---

## 5. Complete the known missing integrations (do not confuse fail-closed stubs with features)

### 5A. T.I.E. `fuse_tie_experience` and object-local usage memory

- Locate real calling graph in `runtime/model_group_preparation.py`, model-group contracts, leases, effect-intent stores, historical attribution and memory owners. Define exact input/output/exception contract and authority boundary from existing code/design docs.
- Implement the actual `fuse_tie_experience` function in its intended owner; replace the defensive `NotImplementedError` **only after** a functioning implementation and acceptance tests exist. Do not create a dummy success function or default `tie_bindings` to an empty no-op.
- Verify resource leases/cost accounting, deterministic ordering, provenance, cross-project isolation, memory persistence, idempotent intent publication, rollback and crash recovery. Test with nonempty `tie_bindings` through the *actual* compilation/dispatch path.
- Include legacy data attribution explicitly; unknown provenance is held or quarantined, never silently assigned to a new project.

### 5B. WorkflowStudio, group/effect transport and authenticated approvals

- Trace WorkflowStudio UI → serialized workflow → API/router → owner/executor → event/state receipts. Reconcile group-node routing, validated effect transport, dynamic group membership, cancellation and resume.
- Inventory **every approval producer and consumer**. `approved_by` may be a display/audit field but must **never** alone grant an effect. Validate signed capability/trust chain, exact project/task/effect scope, expiry/nonce, consent, replay defence, role binding, and revocation.
- Negative tests: missing/forged/expired/replayed approval; confused deputy; changed owner/group; stale UI state; canceled parent; invalid effect during resume. Prove denial before any actual effect.
- Human approval tests must use an authorized reviewer, not auto-generated "approved" fixtures as proof of a live privilege gate.

### 5C. AgentRuntimeController, mesh orchestration and remote member outcomes

- Integrate group creation, dispatch, status, member identity, remote placement, execution-context provenance, deadline, cancellation, settle/dedup, durable receipts, recovery and cleanup across UI/API/worker/provider boundaries.
- Negative tests: lost member, stale job, restart during settle, duplicate acknowledgement, network partition, wrong member outcome, unsupervised remote launch, parent cancellation, orphan child, partial group success.
- Prove real owned execution path with observed artifact/outcome correlation. A test of a helper not called by the product does not establish this workstream complete.

### 5D. Remaining operational gaps

Revalidate outstanding `operational_gap_ledger.py` entries and the release coverage matrix against current source. A previously reported 251-gap/43-owner count from another session is **historical** unless recomputed. Trace actual dependency users, not only function names; repair incomplete reachable behavior and test it. Do not expand scope by importing unused reference-only features unless approved product contracts require them.

---

## 6. Complete all 105 cards by repair group (R01–R11)

Do **not** rely on these summaries instead of the detailed original punch cards; the cards are the authoritative acceptance criteria. For each group, identify exact included finding IDs from the kit rather than inferring ID ranges.

| Group | Required acceptance themes | Must include actual operating checks |
|---|---|---|
| R01 / G01 Source authority | canonical schema ownership, generators, source manifests, complete dependency closure, successor, tool/interpreter resolution | Fresh generation from source and package-readback; reference-worktree reconciliation |
| R02 / G02 Secure persistence | exclusive staging, ancestry pinning, reparse/hardlink denial, WAL consistency, tool intake atomicity | Attack fixtures, process crash/interruption, concurrent writes, restart and outside-canary integrity |
| R03 / G03 Containment | native Job custody, child enrollment, read-only/sandbox/network boundaries, attestation | Actual Windows tree including grandchildren, freeze/terminate, no escape, denied/absent host |
| R04 / G04 Events | atomic batches, unique IDs, protected chain recovery, finite JSON, UI isolation/redaction | Concurrent append, tamper vs authorized interruption, restart/replay, UI/Node consumers |
| R05 / G05 Billing | reservation, bounded budget, trusted usage provenance, settlement and cancellation | Python↔Node receipts, provider usage (if required/authorized), crash/retry exactly once |
| R06 / G06 Lifecycle | execution context, deadlines, cancellation, resume, effect idempotency | Real agent/workflow pause/cancel/restart with owned descendants and stale-work denial |
| R07 / G07 Providers | routing, streaming framing, partial failures, retry, voice/adapters, billing and cleanup | Real parsers/consumers and supported credentialed routes with explicit budget approval |
| R08 / G08 Memory/NSAI | durable checkpoint, retrieval, isolation, corrupt inputs, proof | Actual persisted readback, cross-project denial, restart, corrupted-source handling |
| R09 / G09 Scheduling | fairness, resource admission, stale workers, deadline, recovery | Saturation, loss/restart, no duplicate dispatch and bounded orphan cleanup |
| R10 / G10 Paths/test quality | traversal/reparse/encoding, inventory, incomplete markers, retained evidence | Hostile real paths and fixtures; no test allowlist masking reachable incomplete code |
| R11 / G11 Model custody | leases, shared cache, partial startup, retry/reclaim, GPU/CPU resources | Real supported model backend process and cleanup; unavailable lanes remain blocked |

**Exit requirement for each group:** exact card denominator reconciled; no applicable card left `UNASSIGNED`; repairs pass causal, negative, integration and applicable operating tests; independent reviewer either closes or explicitly records residual problems. A "mostly green" subsystem is not automatic closure of every card in its group.

---

## 7. Three external/architecture blockers — resolve without corrupting authority

### 7A. Canonical signed successor authority — true external blocker

Resume14 reports `missing_owner_policy_authority`: no verified project-revision-succession policy issuer/trust artifact/verifier configured. Trusted public release/effect grant keys exist, but corresponding private authority is deliberately external; existing host SSH keys do not match.

**Agent may do now:** inspect the native policy schema, verifier and trusted fingerprint expectations; document the exact safe owner action and artifact ingress path; run *negative* tests with fixtures and clearly label them synthetic; complete every unrelated R01–R11/R13 implementation task. **Do not** manufacture trust by creating an arbitrary signing key, enrolling your own key without owner authorization, using a test key in release, copying historic signatures, or weakening guards.

**Owner-required action:** locate the legitimate trusted signer / authorized security owner, arrange signing of the actual successor policy for the exact project and revision, and present only the *public* trust artifact or authorized issuance interface to the agent. **Never request the private key or paste secrets into chat/repo.** If no signer exists, escalate to the project trust authority for an explicitly governed bootstrap/rotation procedure; no certificate until resolved.

**Gate release condition:** native validation of real owner policy/signature/fingerprint and exact predecessor-bound authorization, with tamper/replay denial evidence.

### 7B. Closed September campaign has null `project_id`

The predecessor reportedly has `phase=installed_operational`, `intake_open=false`, and `unresolved=[]`; it already passes phase checks. The blocking field is `project_id=null`, while canonical project `prj_pacify-x` exists. **Do not rewrite the historical campaign bytes.**

**Work:** inspect succession schema and migration owner; propose an append-only, independently reviewable association/attestation or authorized legacy-identity recovery that preserves predecessor hash and chain custody. Require explicit owner approval if the action changes provenance. Verify mismatched-project, missing-project, tampered-binding and replay refusal. Persist an authorized recovery receipt and then re-evaluate `validate_successor_proposal`.

**Gate release condition:** predecessor remains byte-identical; canonical verifier accepts a properly authorized linkage without falsifying history.

### 7C. Atomic namespace migration `.engineering-bootstrap` → canonical namespace

A previous one-consumer edit broke commissioning/lifecycle resolution and was reverted. Resume14 states **61 of 1,435** retained test-evidence receipts embed `.engineering-bootstrap`; those counts require re-verification.

**Do this as one migration design, not a string replace:** enumerate every writer, reader, cache, install bootstrap, process, validator, packaging rule and historical receipt; distinguish current writable namespace from immutable historical reference. Design compatibility resolution (e.g., read-only legacy lookup, explicit versioned migration metadata) based on real contracts; dry-run on copied project; build deterministic old→new mapping; audit digest continuity; stage atomic writer and reader cutover with rollback; verify new commissioning, existing project, restart and historical receipts. Obtain owner approval when mandated by governance. Never rewrite immutable receipt contents to make assertions pass.

**Exit:** new canonical state is written and read consistently, legacy evidence remains verifiable, and rollback is proven. The two blocked namespace records close only then.

---

## 8. Source freeze and generated-projection reconciliation

**Do not freeze yet:** engineering, worktree reconciliation, and the first-kit card dispositions must reach a bounded release-candidate state; the owner must authorize the required freeze/admission. The known *196 published vs 203 source* ownership difference is an intentionally visible drift under open intake, not a license to suppress validation.

1. Confirm all executable source repairs (including T.I.E./WorkflowStudio/mesh), user-edit reconciliation and applicable 105-card implementations are completed and inspected; record anything awaiting external authority.
2. Obtain verified signed successor activation and authorized freeze through native project-revision-succession owners, preserving closed September history and proving predecessor binding.
3. Freeze one exact source identity; snapshot digests, tree, dependency/package manifests and current environment; do not alter it outside controlled reopen.
4. Run the **one canonical projection reconciliation** from frozen source owners: contract ownership (currently missing seven model-group entries), provider route index, effect/python/dependency ownership, schemas/fixtures, reachability, source identity and release packaging maps. Regenerate with canonical builders; no hand-edited JSON/hashes.
5. Verify 203 source contracts (or the **actual frozen count**, if intentionally changed) are reconciled with the published registry *and* that the source corpus is genuinely complete, not merely internally consistent. Check missing/unexpected/duplicated rules, import and installed availability.
6. Run `validate_registry`, generated/structural integrity, ownership, provider routes, tool intake, model-group and neighboring tests. Any failure reopens the appropriate owner/card; refresh the frozen source only through the documented revision cycle, invalidating affected receipts.

**Why the order matters:** the Resume14 drift causes seven corpus errors, source-only registry test failure, `validate_registry` failure, downstream `environment-discovery`/tool intake block, and stale provider index reports. Treat these as **one tracked causal chain**, not five unrelated product failures or fake green gates.

---

## 9. Required release pipeline (R12/R14) — no shortcuts

Use `docs/repair/ROLLOUT_COMPLETION_PLAN.md`, `runtime/certification_contract.py`, the native finalizer and `AGENTS.md` for actual commands/admissions. Do not invent project-specific CLI commands if the source defines different ones.

1. **Preflight:** read-only validate all 105 card dispositions, additional kit status, source/campaign identity, signer/recovery, ownership, test profile, missing services/credentials, host prerequisites, resource budgets, installed toolchain and independent reviewer availability. Report all missing requirements in one matrix; no false PASS.
2. **Governed sections:** run every required real section/group for the exact frozen revision, including native Job containment, secure persistence, real workflow, event integrity, billing and UI. Retain original stdout/stderr/exit/PID, start/end, artifacts and hashed receipt; no fixtures masquerading as live host evidence.
3. **Full profile:** use the *native owned sequence*, reportedly `python -m runtime.cli test-profile run full`, followed by the *native owned* `python -m runtime.cli validate`. Resume14/older plans require **one owned execution of each** for a candidate. On failure reopen/repair then create a new eligible candidate and repeat under the actual governance rules; never hide a failed full run.
4. **Package:** build wheel + sdist + VSIX (as required by real project), from the same frozen revision; verify version, dependencies, package data, manifests, digests, policies and source identity. Exclude secrets, user worktrees, retained beta receipts, transient caches, test debris. Preserve previous working release and rollback artifact.
5. **Installed Python acceptance:** clean isolation, install wheel/sdist, check imports and contract file access resolve from **site-packages**, exercise CLI validation/new-project and existing-project commissioning, restart and uninstall/rollback. Do not set `PYTHONPATH` to repo for acceptance.
6. **Installed VSIX acceptance:** actual VS Code extension install/start; command registration, Node↔Python transport, workflow controls, approvals, state persistence, uninstall/upgrade, and failure-recovery. Test real supported VS Code host; a compiled VSIX alone is insufficient.
7. **Real operational scenarios:** actual local agents and workflows; mesh member execution; group node/effects; cancellation/deadline/restart; real Windows Job tree/freeze/termination; secure file and WAL crash recovery; event/UI streaming/redaction; memory/NSAI; T.I.E. nonempty fusion and model-resource accounting; configured provider streaming and billable usage when approved. Bind all observed receipts to the *installed package digest*.
8. **Day1 commissioning and history:** create a fresh authorized Day1 project/campaign/evidence namespace, leave beta/September receipts read-only; migration dry-run/rollback and accepted state ownership.
9. **Independent review:** a qualified reviewer independent of the implementation changes reviews every required card/owner and release gate; store signed/attributable verdicts per actual policy. No automated self-review substituted for human/independent identity requirements.
10. **Final native certificate:** only the canonical finalizer can produce a valid release certificate. Verify source/revision/configuration/package hashes, successor chain, reviewer attestations and revocation handling. If blocked, state **NOT CERTIFIED**.
11. **Only after validation and authorized approval:** merge and push explicitly selected commits, with separately admitted network operation and independently checked remote SHA. Publish/install final VSIX only after gate approval and user-requested sequencing. An installation rehearsal may precede certification under controlled staging; production delivery must not.

**Hardware/network limitation:** no live catalog/inference proof yet. Previous localhost probe timed out and lacked declared network effect. Before retry: obtain precise network/service admission, supervise process custody, enforce timeouts/cleanup, confirm selected lightweight asset/backend and budget. **Do not auto-load 30B or launch `llama-server.exe` under ordinary repair admission.** If live/provider/hardware proof is mandatory but unavailable, that gate remains blocked.

---

## 10. Additional-kit reconciliation (R13)

**Do not drop this because 105 rows are present.** After first-kit findings meet their acceptance requirements, enumerate the standalone kit's IDs and requirements, compare against the first kit by defect cause and current source (not filename similarity), and produce a second denominator:

- `EXACT_DUPLICATE`: reference already-reviewed first-kit result with proof.
- `SUPERSEDED_WITH_PROOF`: new implementation/contract makes earlier finding non-applicable, reviewed.
- `DISTINCT_APPLICABLE`: implement, adversarially test, integrate, verify operation, independently review.
- `UNRESOLVED`: open with exact owner/action/blocker.

Preserve traceability across both lists. Do not double count resolved causes, discard genuinely distinct acceptance requirements or imply the extra kit is complete merely because the first 105 ledger is complete.

---

## 11. Adversarial end-to-end matrix (minimum categories)

Every applicable case needs **actual entrypoint → operation → observed receipt/output → durable restart/replay → cleanup**; add scenario-specific negative variants.

| Scenario | Success proof | Mandatory negative/failure proof |
|---|---|---|
| First install and new project | commissioned source/state, CLI + extension usable | absent config, denied privilege, rollback |
| Existing project upgrade | no lost history, correct namespace | partial migration, mismatched campaign, old receipt hash |
| Real agent/workflow | output and attributable state/effects | cancel, deadline, duplicate delivery, stale task, restart |
| Mesh/group | complete member tree and outcome association | member lost, remote denial, partial completion, forged receipt |
| T.I.E. and model group | nonempty fusion, leased model, correct memories and charges | failed backend, wrong owner, malformed bindings, memory leak |
| Secure publication | atomic durability after restart | reparse/hardlink attack, concurrent writer, WAL point failure |
| Events/UI | intact, ordered, redacted, bounded delivery | duplicate ID, tamper, observer exception, partial stream |
| Host containment | real child/grandchild custody and cleanup | outside-Job PID, denied inspection, freeze escape |
| Billing/provider | authorized budget, actual usage attributable exactly once | no budget, partial stream, retry/cancel, missing receipt |
| Memory/retrieval | persistence, consistent authorized response | cross-project denial, source corruption, missing claim evidence |
| Scheduling | fair bounded execution, recovered workers | saturation, lost worker, duplicate dispatch |
| Approval and effects | exact signed capability authorizes scoped effect | arbitrary `approved_by`, replay/expired/revoked grant |
| Build/install/VSIX | same digest, clean environment, full host functionality | missing packaged contract, repo import fallback, corrupt upgrade |
| Certificate | independently verified source/artifact/authority chain | altered digest, obsolete revision, revoked authority |

Document platform applicability; do not convert `SKIP` into `PASS`. Any required scenario lacking host/credentials/authority is an explicit release blocker.

---

## 12. Practical order of execution and parallel lanes

**Lane A — proceed immediately without external signer:** evidence inventory; per-card review mapping; R01 reconciliation; nine generated-pending dispositions; T.I.E. fusion; WorkflowStudio transport and real signed approval consumers; mesh/remote member execution; R02–R11 missing adversarial/integration operating checks; R13 analysis preparations; namespace migration *design and dry-run*; clean staged packaging smoke checks (not production cert). Keep the 196/203 drift recorded without early canonical refresh if forbidden by source-freeze policy.

**Lane B — owner/security authority:** discover trusted signing owner/interface; authorize successor policy; authorize append-only legacy project-ID association; approve namespace migration cutover and any required external provider/network/budget/hardware effect. Give the user a short exact request with fingerprint/schema/operation and why, **not** a request for secret keys.

**Lane C — after A and B prerequisites:** activate successor; freeze; regenerate all projections; governed sections; full profile + validate; package; clean install + VSIX; real installed operation; independent review; finalizer; approved merge/push and remote verification.

**Do not wait idle on Lane B when Lane A can proceed safely.** Conversely, do not call C complete while B is open.

---

## 13. Exact stopping and escalation behavior

An agent may stop only when: (a) a required owner signature/authorization is genuinely missing; (b) a demanded live host/provider/hardware capability is unavailable after allowed investigation; (c) an irreversible destructive operation needs consent; or (d) source contracts are genuinely contradictory and no policy resolves them. Even then, finish every independently executable item first.

When escalation is required, write:

```text
BLOCKER_ID:
Gate / exact function:
Observed command, exit and evidence path:
Why the source cannot safely resolve it:
Authorized owner/action required (no secret disclosure):
Parallel tasks still runnable:
After-approval exact verification:
```

Before any limit/compaction or tool interruption, update `SESSION_STATE.md` and record: latest HEAD; changes staged/unstaged/untracked; files backed up; running PIDs/process ownership; last test summary and failure; current card/status; immediate next command; source/host/external authority blockers. Save continuously, not only once at the end.

---

## 14. Objective done definition / final acceptance checklist

The project can be declared complete **only when all are true**:

- [ ] All 105 primary findings have evidence-backed individual dispositions and any required independent closures; no applicable `UNASSIGNED` or unresolved blocking status.
- [ ] All rollout-vs-bootstrap executable differences and missing runtime owner/caller paths reconciled, with a source/packaging completeness receipt.
- [ ] T.I.E. fusion and object-local usage memory genuinely execute end to end (not a stub).
- [ ] WorkflowStudio group/effect path and actual signed approval checks work end to end.
- [ ] AgentRuntimeController mesh/remote-member operations work and recover from adverse cases.
- [ ] Two namespace migration items are resolved by authorized, audit-preserving, rollback-tested approach.
- [ ] Additional R13 kit individually reconciled and distinct applicable work implemented/reviewed.
- [ ] Actual trusted successor policy and predecessor project identity recovered without forged keys or rewritten history.
- [ ] Source frozen through native owner; generated contracts, ownership and provider indexes match *complete* frozen sources; all validation gates green.
- [ ] All required governed section/group receipts correspond to exact frozen inputs; test-profile/full and validate done under owned execution.
- [ ] Wheel, sdist and VSIX built/inspected with complete manifests, versioning and digests.
- [ ] Fresh clean-room Python + actual VS Code installed/operating E2E pass with observed runtime receipts and preserved rollback.
- [ ] Required real network/provider, model/resource and Windows host lanes complete or clearly recorded as blocking, not synthetic pass.
- [ ] Independent reviewer approvals recorded; canonical native certificate issued and independently checked; no stale/revoked authority.
- [ ] Git merge/push only under authorization *after* validation; exact remote SHA confirmed.
- [ ] Final handoff includes all commands, logs, artifact digests, known residual limits and production rollback procedure.

If any required box remains open: **NOT COMPLETE / NOT CERTIFIED**. Publish a precise remaining-item list instead of marketing phrasing.

---

## 15. Copy-paste command for the next coding agent

> **Complete the entire Pacify-X repair, integration, installed verification and certification effort.** Begin in `C:\Users\Ben\Documents\bootstrap_project\Pacify-X` on the actual current repair branch; Resume14 last reported `codex/repair-reconcile-20261025` @ `9583fcd9`, but verify Git status/HEAD and preserve all inherited edits. Read `AGENTS.md`, current `SESSION_STATE.md`, `TRACKING_LOG.md`, `ROLLOUT_COMPLETION_PLAN.md`, the 105-card punch cards, both kit tracking ledgers and this runbook. No reset/clean/bulk replacement. First snapshot source and record evidence, then inspect/fix/review every applicable first-kit finding; implement the still-missing `fuse_tie_experience`, WorkflowStudio group/effect transport and signed approval consumers, AgentRuntimeController mesh and remote member outcomes, object-local T.I.E. memory, R01 pending dispositions, namespace migration design and remaining real operating tests. Use the rollout worktree for semantic reconciliation; do not bulk-port unused reference-only contracts. Run targeted positive/adversarial and actual operating tests, maintain the 105-card ledger and disk handoff after every bounded operation. Preserve the source's known 196-vs-203 ownership drift until the authorized freeze/reconciliation stage; do not doctor generated JSON to make it green. Separately document the authentic signer, append-only predecessor `project_id` association and any network/provider/hardware admission that the actual authorized owner must supply; do not forge trust, touch immutable evidence, or stop unrelated work on their account. After all applicable repairs and authorizations, follow the real native sequence: successor → source freeze → canonical projections → governed section receipts → owned full test-profile + validate → wheel/sdist/VSIX → clean-room install/real VS Code host → full installed E2E → independent review → native certification finalizer → authorized merge/push and remote SHA verification. Reconcile R13's distinct additional-kit findings. Keep updating session state and logs continually. **Never declare completion, certification or readiness without all mandatory evidence; provide exact blockers and keep working on every task that does not depend on them.**

---

### Provenance and limits

This is an **execution plan**, not a claim that the coding work has been performed here. All observed/test counts and source paths were supplied in the Resume14 status; several older R-group acceptance categories were drawn from the ongoing project handoff context. The implementing agent must inspect current repository contracts to confirm commands, state enums, acceptance criteria and governing requirements. A completed runbook is **not** a completed release.
