# Pacify-X — what I need, what is wrong, what is blocking completion

**Date:** 2026-10-27 · **Author:** implementation/verification session
**Status: NOT COMPLETE · NOT CERTIFIED · NOT CLEARED FOR RELEASE.**
Independently reviewed closures: **0 of 105**.

Every figure below was measured against this checkout just before writing.

| | |
|---|---|
| Checkout | `C:\Users\Ben\Documents\bootstrap_project\Pacify-X` |
| Branch / HEAD | `codex/repair-reconcile-20261025` / `9583fcd9` (local, not pushed) |
| Working tree | 18 modified + 66 untracked (largely inherited; preserved) |
| Ledger | valid · last checkpoint `…36239` · 44 execution-log records |
| Contract corpus | 204 contracts, **8 errors — one root cause** |
| Certification coverage | `True / 43 / []` (structural only) |

---

# PART 1 — What I need from you

Only **three** things genuinely require you. Everything else I can do myself.

### 1.1 A signing authority (hard blocker for the whole release)

The project cannot activate a successor revision, close intake, freeze, run governed sections, or issue a certificate without it.

`missing_owner_policy_authority()` →
> *no canonical verified project-revision-succession policy issuer is configured; a signed owner policy trust artifact and verifier are required*

**What I need:** the legitimate trusted signer, or an authorized issuance interface, for this exact project and revision. I need the **public** trust artifact / fingerprint / issuer identity only.

**What I must not receive:** a private key, a pasted secret, or a test key dressed up as a release key. Any of those turns the certificate into a forgery and I will refuse it.

**If no signer exists,** this needs an explicit governed bootstrap/rotation procedure from the trust authority. That is a decision only the project owner can make.

### 1.2 Permission for an append-only link to the closed September campaign

The predecessor campaign is closed and terminal (`phase: installed_operational`, `intake_open: false`, `unresolved: []`) — it already satisfies every phase condition. Its `project_id` is `null`, while a real `prj_pacify-x` project record exists.

**What I need:** approval to create an **append-only** association/attestation linking `prj_pacify-x` to that campaign, or confirmation that an authorized legacy-identity recovery should be used.

**What I will not do:** write `project_id` into the historical campaign file. That rewrites campaign history and invalidates hash custody — the exact class of tampering this project's own evidence rules exist to prevent.

### 1.3 A decision on the namespace migration cutover

`.engineering-bootstrap` → `.agentic_engineering_os_px` cannot be done one consumer at a time. I tried it and reproduced a **state split**: commissioning writes the legacy tree, the canonical tree stayed empty, and lifecycle routing lost the state entirely.

**What I need:** approval to perform the cutover as one atomic change once the dry-run is complete, plus confirmation that immutable receipt contents must not be rewritten.

**What I can do meanwhile:** the full design, the old→new mapping, a dry-run on a copied project, digest-continuity audit, staged rollback. All without touching the live writer.

---

# PART 2 — What is wrong (measured, not assumed)

## 2.1 The one open source failure — and why it must stay red

**Symptom:** contract corpus reports **8 errors**. These are **one** cause:
7 model-group contracts have no published ownership record, plus the resulting count mismatch.

The published registry holds 196 records against 203 source records. Verified detail: `only_committed: []`, `content_diff: 0` — the published registry is an **uncorrupted strict subset**, and the 7 missing entries are exactly the new model-group contracts.

**Causal chain (one fault, five visible symptoms):**

```
published ownership 196 vs source 203
  → 7 corpus errors + count mismatch (8 total)
  → test_build_needs_no_published_registry fails
  → validate_registry red
  → environment-discovery cannot pass
  → tests/test_tool_intake.py blocked at architecture-and-planning
  → provider_route_scan reports index_stale for any edited file
```

**Why I am not fixing it now:** the release plan freezes the revision *first*, then regenerates every projection from frozen source in canonical order. Regenerating mid-intake would publish projections for a revision about to change, and would hide the drift from whoever reviews the freeze. **This is the correct, honest signal. Suppressing it would be the actual defect.**

## 2.2 Defects found and repaired this session (all with red→green evidence)

| # | Defect | Why it mattered | Evidence |
|---|---|---|---|
| 1 | Event-bus lock timeout / deadlock | Concurrency test failed **2 of 3 runs**; lock suite hung. Windows byte-range locks are process-owned, and the heartbeat re-entered a non-reentrant guard. | `resume9-lock-red-before.log`, `-residual-red.log`, 42+10+23 pass |
| 2 | Semantic-entity contract resolved from the wrong root | Owner reported **PUBLISHED**, then could not read back its own registry (`FileNotFoundError`) | `resume14-entity-legacy-resolution.log` |
| 3 | Missing `semantic-entity` contract | Publication validated against a file that did not exist | `resume14-corpus-roundtrip.log` |
| 4 | Fixture generator couldn't build interior constraints | `^pxe1:[a-f0-9]{32}$` was unconstructible; corpus had a permanent failure | 203 schemas / 0 failures |
| 5 | Package-data gap | `contracts/semantic` + `project_revision_succession` shipped in **neither** wheel nor sdist | `pyproject.toml` |
| 6 | T.I.E. imported a non-existent function | Any caller passing `tie_bindings` got a bare `ImportError` from inside plan compilation; nothing tested it | `resume14-tie-path.log` |
| 7 | **My contract accepted unqualified identities** | `entity_id` derives from `qualifier`; without it the identity cannot be re-derived or audited | `treescan-old-contract-qualifier.log` |
| 8 | T.I.E. read symlinked experience logs | A link could present unrelated bytes as a subject's history | `treescan-tie-link-red.log` → green |
| 9 | Ownership generator had no rule for `contracts/semantic` | It silently **guessed** an owner, making my hand-edited registry a second source of truth | `runbook-dir-rules.log` |

## 2.3 Things that are working but not yet proven to release standard

Green component tests are **not** operating, installed, or reviewed evidence. These groups pass their suites but still need real-scenario proof:

R02 hostile paths (94) · R03 containment · R05 billing (18 Py + 20 Node) · R06 lifecycle · R08 memory/NSAI (50) · R09 scheduling · R11 model resources · model-group (41) · T.I.E. fusion (16).

## 2.4 My own errors this session (disclosed, not buried)

- Recorded `AGENTS.md` as **missing** from a failed path lookup. It was present all along and outranks every handoff.
- First generator fix **stripped character classes** — caught by the corpus gate, not by reading the diff.
- Scanned the **Music root**, which holds no `runtime/`, and reported every item absent. Path error.
- Cited `qualifier: "bad qualifier!"` as the contract divergence. **Wrong** — both contracts correctly accept it; the real divergence is a *missing* qualifier.
- Briefly edited the wrong branch while locating code by line number.

The pattern: I make errors and the **gates** catch them. That is why I run gates rather than trusting my own reading.

---

# PART 3 — What is left

## 3.1 Doable now, no authority needed

1. **Port four modules found in the external trees:** `extension/src/agentHarness/durableTaskState.js`, `scripts/rollout/compare_trees.py`, `scripts/rollout/integration_plan.py`, `tests/test_rollout_inventory.py`. These unblock the Node billing suite and the rollout-inventory required suite.
2. **Decide the semantic surface question.** The locator/relation/compact-address/census contracts *have owners* in both external trees — my earlier "unreachable, ignore" disposition was incomplete. Either port owners+contracts+tests as a group, or mark them `RETIRE_WITH_REVIEW` with a stated reason. No ambiguity.
3. **WorkflowStudio approvals (runbook §5B):** inventory every approval producer/consumer and prove `approved_by` alone cannot grant an effect.
4. **Mesh / remote member outcomes (§5C).**
5. **Remaining R02–R11 operating scenarios** (adversarial, integration, restart) on top of the passing component suites.
6. **Namespace migration design + dry-run** (§1.3).
7. **R13 additional kit** analysis, after first-kit acceptance.

## 3.2 Blocked on you

Freeze → governed sections → one full profile + `validate` → package → clean install → installed operation → independent review → certificate → merge/push/VSIX.

Nothing in this half can proceed, and no claim of success may be made until it does.

---

# PART 4 — The honest bottom line

**What is genuinely better than when this handoff arrived:** nine real defects fixed with retained red→green evidence; a status ledger that now spans all 105 findings instead of a five-card subset; certification coverage structurally complete; T.I.E. actually implemented rather than stubbed; and several false claims from earlier sessions corrected against source.

**What has not changed:** there is **no certificate**, **no independent review**, and the project cannot reach a releasable state without §1.1.

**The risk I am most concerned about** is not a bug. It is that this work gets described as "complete" because the tests are green. They are green for the parts I could reach. The release gates are closed, and they are closed for authority reasons, not engineering ones.

**If you give me one thing, make it §1.1.** The rest is time and care. That one is a hard stop.


## Continuation correction: approval boundary and scope (2026-10-27)

The native WorkflowStudio approval boundary is now exercised by 13 passing checks, including real node execution and replay denial; 41 host neighbor checks also pass. See SESSION_STATE for retained receipts and limitations. The rollout compare/integration/inventory modules are already present; the four-module port list above is historical and requires semantic adjudication, not blind copying. Public trust verifies signatures; legitimate signer access or a signed issuance artifact is needed to issue successor authority. Ordinary reversible design and implementation can continue under the existing user authorization. Namespace dry-run and append-only linkage design do not require a new permission question. Remaining engineering work is not reduced to signer availability.
