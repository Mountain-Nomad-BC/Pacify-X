# Day 1 rollout: implementation and certification plan

Recorded 2026-10-24. Status: **repair intake; not certified**.

This supersedes the execution order in `evidence/completion-plan-punch-cards-2026-10-24.md`.
Historical reports remain evidence of their own runs. None authorizes closure of a current finding.
The live execution journal is `evidence/rollout-2026-10-24/SEGMENT_LOG.md`.

## What the inspection established

The candidate is `C:\Users\Ben\Music\Pacify-X-main\Pacify-X-main`, not its outer directory.
It has no Git metadata. The incumbent is `C:\Users\Ben\Documents\bootstrap_project\Pacify-X`,
on `main`, initially clean at `67827f97b9d101befb4007e8ad19757ceeb74455`, with origin
`git@github.com:Mountain-Nomad-BC/Pacify-X.git`. Preserve that history; integrate on a reviewable branch.
The enclosing bootstrap directory also contains an adopted project workspace, plugin/reference
material, quarantine stores, archives, and a separate `COMPLETE_REPAIR_IMPLEMENTATION_PLAN.md`.
Those are not one interchangeable product tree. The owner clarified that external application
examples are learning references only. They are excluded from Pacify-X rollout requirements,
product features and public documentation. The two inspected `projects/pacify-x` directories
contain commissioning/control documents. Their external reference plans are not an additional
application to implement or certify here.

The byte comparison is `evidence/rollout-2026-10-24/source-comparison.json`: 860 changed,
1,780 candidate-only, 4,103 incumbent-only, and 4,884 equal paths at its observation point.
This is a scoped inventory, not a complete custody snapshot. Every pruned directory and omitted
large/binary payload is listed. Source additions made after that inventory require a refreshed
integration manifest. Missing paths are review candidates, never automatic deletion requests.
Many differences are skill/workflow memory, preserved skills, runtime ledgers, screenshots,
and historical evidence. The migration is also a product-wide namespace change:
`engineering_bootstrap` / `.engineering-bootstrap` to `agentic_engineering_os_px` /
`.agentic_engineering_os_px`. It must be tested as a migration, not treated as cosmetic renaming.

The current oracle selects `.agentic_engineering_os_px/processing-order/repair-campaign.json`:
initially phase `intake`, open intake, unresolved `initial-operational-intake`. The supported
begin-repair transition later entered repair while leaving intake and its denominator open. A second legacy campaign
under `.engineering-bootstrap` is in `repair`. Their project IDs differ. The comprehensive
report's `installed_operational` statement is stale. A valid status command does not mean a
valid release. The ledger contains 13 cards, none closed: nine narrowly verified and four
implemented at inspection. Narrow tests are not operational acceptance.

`PROJECT_MANAGEMENT.md` still names final133 and v0.7.0 while package metadata names 0.9.0.
It must be reconciled with the active revision through its canonical owner before release.
`NEXT_STEPS_PLAN` is empty in this candidate. Historical pass-by-pass tracing claims do not
establish current reachability, behavior, wiring, recovery, or deployed execution.

The AST inventory examined 470 runtime Python modules, 5,246 functions and 725 classes,
with zero syntax errors. It found 93 `pass` statements, 29 outside exception handlers,
one `NotImplementedError`, and three marker occurrences. The latter is an abstract backend
method. Most non-handler passes are exception class bodies; three are documented conditional
branches. The exception handlers still need fault/recovery review. These counts are a static
denominator, not proof that 470 modules are correct. Details and hashes are in `runtime-inventory.json`.

The extension's Python resolver already supports an explicit constructor path, project-local
certification environment, and ambient fallback; `pacifyX.pythonPath` exists. Its local
`.venv-certify` and Chocolatey 3.14 launcher refer to a missing `C:\Python314\python.exe`.
A working interpreter is `C:\Users\Ben\AppData\Local\Temp\py3145t\python.exe` (3.14.5).
That temporary path is a diagnostic tool, not a supported rollout default.

Initial readiness failed on the missing pinned Python build package, unfinished campaign,
and three encoding-integrity findings. Encoding has since been repaired; the campaign and
build-environment prerequisites remain open. Node, npm, lockfile, browser, VS Code and Python
probes pass. `npm run check` passes. The initial selected backend set had 99 passes and
one failure in real signed-policy provenance. The initial repair had 100 selected passes. The final integrated focused set has 120 passes,
including actual disposable OpenSSH signing/verification, tamper rejection, native schema
admission, ownership-builder coverage and clean-checkout custody regressions. The broader
runtime-domain-contracts gate failed in six of fifteen chunks; see section-failure-summary.json.
No current passing section receipt is claimed.

## Completion rules

Every card has one accountable owner, explicit effects and admission, named producer and
consumer, failure and recovery behavior, evidence paths, dependencies, rollback and residual
limits. `planned`, `implemented`, `focused-pass`, `operational-pass`, and `closed` are distinct.
An unrun, skipped, hung, stale, simulated, optional-only or indeterminate required lane blocks
release. Do not populate a receipt by declaring a claimed stage passed. Do not resolve the
placeholder finding until it is replaced by a complete, evidenced intake denominator.

All implementation and optimization precedes repair freeze. The permitted sequence is:
intake and repairs -> explicit intake closure -> operational verification -> repair freeze ->
one generated/source reconciliation -> current sections -> one owned full profile -> one
validation -> one package -> one exact-artifact install -> installed operational testing ->
one certification. Source changes after freeze invalidate downstream proof and require the
registered reopen/successor mechanism. Never rewind a completed beta campaign by editing JSON.

## Ordered punch cards

### D1-01 - Custody and reconciliation (owner: repository integration)

Dependencies: none. Effects: read, local writes; separate network admission for remote fetch/push.
Retain original HEAD, candidate manifest, exclusions and dirty-state observations. Compare bytes
and Git-normalized text separately. Classify each difference as authored source, generated
projection, runtime state, historical evidence, vendored asset, managed-project data or unknown.
Preserve incumbent-only files; resolve duplicates at canonical owners. Export source only to a
new branch/worktree, with per-file preimage and postimage hashes. Detect links, traversal,
concurrent source/destination edits, secret material and unexpectedly large files. Never copy
the candidate's active ledger, quarantine, private keys, local credentials, caches or installed
extensions into the repository. Exit: reviewable integration manifest, diff, rollback reference,
and a successful branch push. Rollback: discard the integration branch; original main remains.

### D1-02 - Real intake and historical obligations (owner: audit/control plane)

Dependencies: D1-01 inventory. Read the 13 live gap cards, latest report30 queue and full feature
acceptance requirements; preserve every unverified interaction-chain item. Extract applicable engineering
lessons from the parent plan without importing external application requirements.
Include current test failures and source divergence, not just grep findings. Build a finding
register with severity, reachability, producer, consumer, proof required and supersession links.
Register it using the campaign/ledger APIs under exact admissions. Exit: zero unclassified
current findings and a finite unresolved denominator; unresolved items remain open.

### D1-03 - Namespace and installed-package migration (owner: runtime/package)

Dependencies: D1-02. Trace canonical root resolution in source, installed wheel, console script,
VS Code, MCP, workspace adoption and persisted records. Pick the renamed namespace as the
target only after proving backward-compatible reads and explicit migration of old state.
Reject conflicting simultaneous identities. Preserve old records and data by immutable snapshot;
make migration idempotent and recoverable. Test source/installed imports, both commissioning
modes, project isolation, registry paths and Windows/POSIX paths. Gate: runtime-domain-contracts
and affected execution/extension sections. Exit: one selected owner and tested compatibility
contract. Rollback: restore preimages through the migration journal.

### D1-04 - Real successor authorization (owner: succession/trusted evidence)

Dependencies: D1-02. Align JSON schemas, exact runtime field validation, revocation registry,
signature namespace/serialization, source digest and policy evidence. Use actual signed disposable
fixtures; test expired, revoked, superseded, replayed, tampered and wrong-project inputs.
The current repair admits the registry field, adds missing authorization fields, fixes the SSH
line terminator and proves signed success plus tamper rejection. Native schema IDs/dialect and ownership-builder mapping are also repaired. Their generated
registry remains intentionally pending canonical reconciliation. Remaining: complete revocation
freshness rules, schema/runtime parity negatives, activation through the real CLI and trusted
evidence owner. Production policy/key issuance remains the external canonical owner's action;
do not mint trust or self-attest a verifier. Rollback: reversible source/schema patches.

### D1-05 - Complete revision lifecycle (owner: revision campaign)

Dependencies: D1-03/D1-04. `revision_campaign_lifecycle.py` currently supports begin/register/resolve.
The original `close_repair_intake` and `freeze_repair_campaign` rejected successor revisions.
The 2026-10-25 repair now shares validation and dispatches those operations to the transactional
revision owner, with real WAL publication/recovery tests. Later stage namespace parity remains open.
Implement transactional revision-aware closure, operational evidence validation, freeze,
reconciliation, section/release receipt lookup and stage transitions at their canonical owners.
Share validation logic with legacy flows; preserve predecessor bytes. Test WAL interruption at
each campaign/policy/pointer publication, recovery, stale before-images, concurrent writers,
missing files, corrupt journals, unauthorized scope, repeat invocation and A->B->C lineage.
Exit: one revision can complete the entire governed lifecycle in an isolated integration fixture;
no bypass flags or handcrafted state. Gate: testing-governance plus runtime-domain-contracts.

### D1-06 - Native producer custody and workflow fencing (owner: effect owners)

Dependencies: D1-02. Finish the exact queue referenced by PX-GAP-0011/report30. Enumerate every
real mutating producer, require its exact native host scope and admission before execution,
register resources/processes when created, settle custody on success/failure/timeout/cancellation,
and fence workflow effects before subprocess dispatch. Test denied writes leave all protected
stores unchanged. Test successful retries and restart reconciliation. Exit: complete owned
producer denominator with fault evidence, not a generic wrapper-only green test.

### D1-07 - Portable interpreter and environment (owner: extension/release environment)

Dependencies: D1-03. Keep explicit VS Code setting and owned launcher semantics consistent;
honor the documented environment variable only at intended entry points. Detect a broken local
venv before launch and report an actionable error without invoking a billable provider. Build a
durable isolated environment from pinned requirements; never commit a machine-specific path.
Test absent/broken venv, spaces, explicit path precedence, ambient fallback and dependency probes.
Exit: source, owned host and installed extension resolve the same admitted interpreter.

### D1-08 - Provider/model fabric and offline behavior (owner: providers)

Dependencies: D1-06/D1-07. Trace catalog -> selector/router -> admitted provider -> actual response
-> status/evidence. Cover all bridged lanes, unavailable credentials/models, exhausted budgets,
timeouts, stream/tool protocol translation and CPU fallback. Simulation must remain visibly
simulation and cannot satisfy live readiness. Run fault tests before rebuilding the route scan.
Rebuild `scripts/build_provider_route_index.py --admission-event-id <current-id>` through its
guarded publisher only when source writers settle; its registry/runtime-core/resource-lifecycle
effects require explicit scope. Exit: no unexplained direct provider routes or false readiness.

### D1-09 - UI and host integrations (owner: extension)

Dependencies: D1-03/D1-06/D1-08. Verify action inventory -> renderer -> dispatcher -> runtime owner
-> visible outcome, including sandbox settings, model selection, Studio, memory/graph,
coordination, cleanup, project selection, approvals and failure states. Run unit, both browser
lanes, performance and disposable VS Code host lanes. Test unavailable backend and stale
fingerprints. Gate: corresponding registered section; retain operational proof for each control.
Exit: complete required control denominator and real installed-host results.

### D1-10 - Static findings and reliability (owner: runtime)

Dependencies: D1-02. Use the 470-module AST inventory to review handler suppression, explicit
unsupported branches, protocol adapters, orphan modules, cycles and duplicate implementations.
Prioritize reachable failures, data loss, authorization and falsely successful return values.
An exception subclass `pass` and an abstract method are dispositions, not repair targets.
For each real defect add a causal fault/recovery test; benchmark measured hot paths before
optimization. Exit: every candidate disposition has owner/reachability/evidence; no invented
global completeness claim from source scanning.

### D1-11 - Fresh Day 1 state and data boundary (owner: commissioning/privacy)

Dependencies: D1-03/D1-05/D1-06. Build a new isolated commissioning root through the supported
new-project/registration APIs and bind a new rollout identity. Separate product source,
immutable beta evidence, local operational custody, optional user migration and new rollout
receipts. Do not reset/delete beta data to obtain green tests. Defaults must not import old
skill usage, memory, credentials, budgets, project selection or release claims. Verify a clean
install and an explicit opt-in upgrade both preserve existing user data. Test idempotency,
rollback, no cross-project retrieval and no historical receipt reuse. Exit: fresh state plus
documented optional migration; version metadata is consistent across Python/VSIX/docs.

### D1-12 - Compliance, encoding and dependencies (owner: release compliance)

Dependencies: D1-02/D1-07. Repair the three current encoding findings through the encoding
verifier's exact report. Verify licenses/notices/privacy/provider handling against actual shipped
behavior. Install pinned build tools into the durable isolated environment, compare lockfile and
installed metadata, and run the repository's dependency/security tooling. Advisory claims need
current source data; do not infer security from pins alone. Exit: readiness prerequisites green
apart from intentionally unfinished release stages. No unsupported platform claim.

### D1-13 - Finish repairs and operational verification (owner: campaign)

Dependencies: D1-02 through D1-12. Run changed-section gates during repair, preserving failures.
Reconcile every finding with implementation and behavioral evidence; independently verify
protected-store immutability, no escaped processes/workspaces, and real operational outcomes.
Only after the complete denominator is zero, explicitly close intake through the canonical API
and produce the owner-issued hash-bound operational receipt. Exit: operational verification
accepted, no unresolved required findings, explicit intake closure. Do not freeze while a required
Pacify-X finding or trust input remains missing.

### D1-14 - Freeze and reconcile once (owner: source identity)

Dependencies: D1-13. Freeze via supported campaign API, retain restorable source identity and
clean Git commit. Reconcile deterministic projections using canonical guarded builders,
including provider routes, test index, Studio mirrors, architecture/registry graphs and version
metadata. Use the intended parser/interpreter identity. Do not edit generated hashes manually.
Exit: one source identity and complete canonical generator receipts. Any further repair invalidates
this attempt according to the registered campaign contract.

### D1-15 - Current governed sections (owner: test orchestration)

Dependencies: D1-14. Enumerate current `registry/test_profiles.json` rather than hardcoding a
historical section count. Run `python -m runtime.cli test-section run <section>` for every required
section using the owned orchestrator. Prove source/dependency/parser hashes, denominator and
resource closure. Exit: all required receipts current against the frozen identity; no skipped
required groups. Failed owners remain failed; use canonical repair/reopen rules.

### D1-16 - Single full profile and validation (owner: release-stage owner)

Dependencies: D1-15. Use `scripts/run_release_candidate.py` and the canonical stage config to
own exactly one `python -m runtime.cli test-profile run full`, then one `python -m runtime.cli
validate`. No raw unittest substitute, no simultaneous competing owners and no speculative
retry. Capture command, environment, monotonic timing, exit status, test counts, complete logs,
source digest and custody settlement. Exit: both owner receipts accepted and identity unchanged.

### D1-17 - Exact package and installed proof (owner: release/install)

Dependencies: D1-16. Admit package/install separately, create one immutable wheel/source/VSIX
set, inspect shipped contents, licenses, secrets, beta-state absence and identity. Install those
exact bytes into disposable clean roots, verify installed hashes and run commissioning plus
registered installed operational owner across required platform/browser/hardware lanes.
Unavailable required platforms block their support claim. Exit: artifact/install/control
denominators closed, rollback package retained, no leaked child or workspace custody.

### D1-18 - Certification and rollout publication (owner: certification)

Dependencies: D1-17. Validate the candidate/stage configuration pair with
`scripts/validate_certification_pipeline.py` before consuming the attempt. Complete the canonical
atomic digest-bound finalizer once; signature binds source commit, exact artifacts, evidence,
platform scope and trust chain. Historical certificates remain archived/revoked as appropriate.
Push reviewed source branch and verify remote SHA. Publishing a GitHub/Marketplace release is
a distinct action from pushing development source and must use the exact certified artifacts
and applicable publication authority. Exit: verified remote refs/assets, installation instructions,
rollback drill and certificate that the verifier accepts for those bytes.

### D1-19 - Product scope and reference hygiene (owner: documentation/provenance)

Dependencies: D1-02. Keep rollout scope strictly to Pacify-X bootstrap/control-plane capabilities.
Reference examples may inform mechanisms, but do not appear as included applications, product
requirements or certified features. Remove example product names from active documentation.
Inventory old imported provenance in `registry/plan_corpus.json` and content-addressed planning
corpora. Externalize raw reference metadata through the canonical recoverable custody owner;
regenerate active projections after repairs settle. Preserve authenticated historical bytes
outside the rollout payload rather than silently changing content-addressed provenance.
Test that wheel/source/VSIX exports contain no reference application branding or live example
state and that the retained provenance index remains verifiable. Exit: public documentation,
packaged context and advertised capabilities describe Pacify-X only; historical custody is
accessible separately and cannot satisfy current certification.

### D1-20 - Continuation and independent review (owner: each segment owner)

Dependencies: continuous. Append one segment record after every material unit: active gap,
checkpoint/admission IDs, exact files, findings, commands/results, artifacts/hashes, unresolved
items and next action. Update the machine card state with evidence references; never mark a
card closed from prose alone. Close expired/superseded sessions through the ledger API.
At handoff record Git branch/HEAD/remote, dirty state, live child IDs, environment resolution
and exact next command. Independent review must challenge success/false-readiness, data
isolation, signing, recovery and receipt freshness before certification.

## Resume instructions

Read this document, `SEGMENT_LOG.md`, and current Git status. Use actual current state,
not the historical checkpoint numbers embedded in old reports. Read the canonical ledger
snapshot, close superseded sessions, checkpoint the same active card (or perform its explicit
handoff), admit exact effect scopes and run `guard-work` for each effect. Read/network/install
and source effects are separate where required. The current user has already authorized
implementation, local rollout preparation and source push; do not ask for that authorization
again. External signed policy evidence cannot be invented from conversational approval.

Keep repairs active until their prerequisites are satisfied. A failed readiness check is useful
evidence; it is not permission to bypass the release-order oracle. The commands in D1-15..D1-18
are conditional on their prerequisites, not a shell script to run blindly today.
