# Blocker register — Pacify-X

Every entry uses the runbook's escalation form. Only these are external; everything else is ordinary engineering work and is being done.

---

## BLOCKER-001 — No canonical signed owner authority

**Gate / exact function:** `runtime.project_revision_succession.missing_owner_policy_authority()` → `validate_successor_proposal()`; blocks signed successor activation, intake closure, the freeze, all governed sections, and therefore the certificate.

**Observed command, exit and evidence path:**
```
.\.venv-repair\Scripts\python.exe .tmp\resume9\owner_auth.py
SuccessionProposalBlocked: no canonical verified project-revision-succession policy issuer
is configured; a signed owner policy trust artifact and verifier are required
```
Evidence: `docs/repair/evidence/` (owner-policy probe), `SESSION_STATE.md` segment 4.

**Why the source cannot safely resolve it:** Signature verification requires the enrolled public verifier. Issuing a new trusted policy requires legitimate signer access or an authorized issuance interface; its private key stays outside this repository. Public trust anchors exist (`release-trust.json`, `effect-grant-trust.json`) but no matching signing authority is reachable. Any locally generated key would be a forgery presented as trust, and would make the certificate meaningless rather than obtained.

**Authorized owner/action required (no secret disclosure):** the owner locates the legitimate trusted signer / authorized security owner and arranges signing of the successor policy for this exact project and revision. Only the **public** trust artifact, fingerprint, or authorized issuance interface is needed. **Do not send a private key.** If no signer exists, escalate to the project trust authority for an explicitly governed bootstrap/rotation procedure — no certificate until resolved.

**Parallel tasks still runnable:** all of Lane A (R01 reconciliation, per-card disposition, T.I.E., WorkflowStudio, mesh, R02–R11 operating checks, R13 analysis, namespace migration design/dry-run, staged packaging smoke checks).

**After-approval exact verification:** `validate_successor_proposal` accepts with real signature + fingerprint + predecessor binding; tamper/replay/expired/revoked fixtures are refused; then freeze and governed sections.

---

## BLOCKER-002 — Closed September campaign has `project_id: null`

**Gate / exact function:** `validate_successor_proposal()` — `predecessor project identity is required`.

**Observed command, exit and evidence path:** the predecessor campaign at `.engineering-bootstrap/processing-order/repair-campaign.json` has `phase: installed_operational`, `intake_open: false`, `unresolved: []` (so it **passes** every phase condition) and `project_id: null`. A real `prj_pacify-x` project record exists. Evidence: `docs/repair/evidence/` campaign probe; `TRACKING_LOG.md` Resume14 segment 4.

**Why the source cannot safely resolve it:** back-filling `project_id` would rewrite historical campaign bytes and invalidate its hash custody. The runbook forbids that, and so does the evidence-integrity rule that other parts of this project depend on.

**Authorized owner/action required:** approve an **append-only** association/attestation (or an authorized legacy-identity recovery receipt) that links `prj_pacify-x` to the closed campaign without altering the predecessor's bytes, plus explicit owner approval because it changes provenance.

**Parallel tasks still runnable:** the full Lane A list; the association design can be prepared and negative-tested with synthetic fixtures now.

**After-approval exact verification:** predecessor bytes byte-identical (hash unchanged); canonical verifier accepts the authorized linkage; mismatched-project, missing-project, tampered binding and replay cases all refused.

---

## BLOCKER-003 — Namespace migration is atomic, not per-consumer

**Gate / exact function:** the 2 `NAMESPACE_MIGRATION_REVIEW_REQUIRED` records in the R01 adjudication; `runtime/engineering_os_paths.control_path()` vs the commissioning owner's writer.

**Observed command, exit and evidence path:** pointing only `tool_intake` at `control_path()` reproduced a **state split** — commissioning writes `.engineering-bootstrap`, the canonical tree stayed empty, and `lifecycle_status` lost the state. Reverted. Evidence: `docs/repair/evidence/resume14-namespace-probe.py|.log`.

**Why the source cannot safely resolve it in one edit:** 61 of 1435 retained test-evidence receipts embed the literal legacy path (measured; re-verify before cutover). Migration spans the commissioning writer, its callers, caches, install bootstrap, validators, packaging rules and historical receipts, and changes where authoritative state lives — a provenance change.

**Authorized owner/action required:** approve the cutover design and any governance-mandated migration (per runbook §7C); confirm that immutable receipt contents must **not** be rewritten.

**Parallel tasks still runnable:** enumerate every writer/reader/cache/validator, build the deterministic old→new mapping, dry-run on a copied project, audit digest continuity, and stage a rollback — all without touching the live writer.

**After-approval exact verification:** new commissioning writes and reads canonical state consistently; existing projects still resolve; restart works; historical receipts still verify; rollback proven.

---

## Not blockers (being worked, per runbook §0.6)

- 196 published vs 203 source ownership drift — **expected under open intake**, preserved deliberately until the freeze.
- Seven corpus errors, `validate_registry` red, `test_tool_intake` blocked at `architecture-and-planning` — all one causal chain from that drift; they resolve at the freeze, not before.
- 9 `PORTED_COMPONENT_TESTED_GENERATED_PENDING` records — reviewed this session; see `RECONCILIATION_MATRIX.csv`.
- T.I.E. `fuse_tie_experience` — real feature work, in progress as Lane A.
- Live catalog/inference probe — needs a separate network/service admission and owned process custody; not attempted here.


Continuation: the native workflow approval boundary has 13 passing direct API checks and 41 host neighbors. Remote integration remains open: missing prepared-group workflow owner resolution and execution mode are documented in WORKFLOW_APPROVAL_AND_REMOTE_INTEGRATION_2026-10-27.md. Authority availability is not the only unfinished work.
