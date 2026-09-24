# Release Compliance Checklist

The release gate. A release does not proceed while any **required** item is unmet.

Items are marked so the gate can eventually be machine-checked. `[auto]` = enforced by a script
today; `[manual]` = human review; `[item]` = required but its automation is an open repair item.

---

## 0. Processing-order rules (non-negotiable)

- [ ] Everything that contributes to release identity is generated **before** the freeze.
- [ ] Certification is **read-only** with respect to the governed candidate.
- [ ] No compliance artifact (SBOM, notices, provenance, docs, closure report) is generated
      **after** the freeze; doing so changes the released bytes and invalidates certification.
- [ ] Convergence is demonstrated (a second deterministic generation pass produces no unexpected
      change) before the freeze.

## 1. Gate — repository invariants `[auto]`

- [ ] `python scripts/verify_release_invariants.py --root .` → **valid**
      - [ ] no PX-operated remote endpoints
      - [ ] no production remote telemetry
      - [ ] no unapproved model download
      - [ ] no shipped secrets
      - [ ] no machine-specific paths or PII
      - [ ] policy-only invariants reviewed
- [ ] `python scripts/audit_local_paths.py --root .` → **0 findings**
- [ ] extension: `npm run check` → passes (includes the telemetry guard)

## 2. Gate — policy/document presence `[auto][item]`

Required at repository root:

- [ ] `LICENSE`
- [ ] `NOTICE`
- [ ] `SECURITY.md`
- [ ] `PRIVACY.md`
- [ ] `TELEMETRY.md`
- [ ] `DATA_FLOW.md`
- [ ] `THIRD_PARTY_NOTICES.md`
- [ ] `MODEL_AND_DATA_LICENSES.md`
- [ ] `TRADEMARKS.md`
- [ ] `DISCLAIMER.md`
- [ ] `INTENDED_USE.md`
- [ ] `HIGH_RISK_AND_CONSEQUENTIAL_USE.md`
- [ ] `AI_TRANSPARENCY.md`
- [ ] `AI_LIMITATIONS.md`
- [ ] `DATA_RETENTION_AND_DELETION.md`
- [ ] `PROVIDER_DATA_HANDLING.md`
- [ ] `MEMORY_PRIVACY_MODEL.md`
- [ ] `CODE_OF_CONDUCT.md`
- [ ] `CONTRIBUTING.md`

Required under `docs/`:

- [ ] `docs/security/{THREAT_MODEL, SECURITY_ARCHITECTURE, SECURE_UPDATE_POLICY, VULNERABILITY_RESPONSE, INCIDENT_RESPONSE, SUPPLY_CHAIN, SBOM_POLICY}.md`
- [ ] `docs/compliance/{COMPLIANCE_SCOPE, REGULATORY_APPLICABILITY_MATRIX, EU_AI_ACT, EU_CRA, GDPR, US_FEDERAL, US_STATE_AI_PRIVACY_MATRIX, ACCESSIBILITY, EXPORT_CONTROL_REVIEW, RELEASE_COMPLIANCE_CHECKLIST}.md`

**Status:** presence is not yet automated; a presence check script is a repair item.

## 3. Gate — stale version references `[item]`

- [ ] no document references a version that is not the current release line
- [ ] `pyproject.toml`, `extension/package.json`, and the README versions agree where they should
      (the extension has its own line and that is documented)
- [ ] no document describes a superseded release as current

## 4. Gate — dependency, licence, and model inventory `[item]`

- [ ] `THIRD_PARTY_NOTICES.md` matches the actual dependency manifests
- [ ] `MODEL_AND_DATA_LICENSES.md` is present and every bundled/used component is accounted for
- [ ] no unlicensed copied asset
- [ ] no incompatible licence detected
- [ ] model records carry source, licence, revision, hash

## 5. Gate — security `[auto][item]`

- [ ] secret scan clean (tree) `[auto]`
- [ ] secret scan clean (git history) `[item]`
- [ ] secret scan clean (packaged VSIX and evidence) `[item]`
- [ ] dependency vulnerability scan run `[item]`
- [ ] SBOM generated `[item]`
- [ ] build provenance generated `[item]`
- [ ] artifact hashes computed and published `[item]`
- [ ] threat-model delta reviewed `[manual]`
- [ ] plugin permission delta reviewed `[manual]`
- [ ] network endpoint delta reviewed `[auto]` (invariant)
- [ ] vulnerability reporting path present `[manual]`

## 6. Gate — privacy `[auto][manual]`

- [ ] data inventory matches code `[manual]` — reviewed against the runtime-truth scan
- [ ] telemetry manifest matches code `[auto]` — invariant + guard, currently "none emitted"
- [ ] retention matches code `[manual]`
- [ ] remote endpoint list matches code `[auto]`
- [ ] deletion/export behaviour tested `[item]`
- [ ] private/public memory boundary tested `[item]`

## 7. Gate — AI compliance `[manual]`

- [ ] AI disclosure present and accurate
- [ ] provider/model identity inspectable
- [ ] intended purpose current
- [ ] unsupported high-risk uses current
- [ ] generated-content provenance capability documented where applicable
- [ ] AI claims audit passed `[item]` — the automated `release_claims_gate` is a repair item

## 8. Gate — CRA `[manual]`

- [ ] CRA classification reviewed — **currently an open owner/legal decision**
- [ ] manufacturer/steward status recorded — **open**
- [ ] current reporting obligations recorded
- [ ] vulnerability/incident workflow documented and tested `[item]`

Because the classification is an open decision, this gate **cannot pass silently**: it requires a
recorded decision, not an assumption.

## 9. Gate — Marketplace / extension `[manual]`

- [ ] privacy link works
- [ ] licence link works
- [ ] security link works
- [ ] repository link present, with the note for AI and human review before installation
- [ ] telemetry disclosure accurate ("none emitted")
- [ ] disk/build size disclosure current
- [ ] provider/cost disclosure current
- [ ] screenshots do not expose secrets or private paths
- [ ] extension README matches the repository README's claims

## 10. Gate — generated state `[auto]`

- [ ] `validate_generated_artifacts` → valid (all checks)
- [ ] graph artifacts rebuilt from their authoritative inputs
- [ ] `graph_authority_manifest` reconciled
- [ ] `validate_registry` → valid
- [ ] `px_world_state` rebuilt with the final source revision
- [ ] projections at **fixed point** (second pass produces no unexpected change)

## 11. Gate — tests and certification `[auto]`

- [ ] governed section gates current
- [ ] exactly one full test profile run on the frozen candidate
- [ ] `python -m runtime.cli validate` passes
- [ ] package built and hash recorded
- [ ] install verified
- [ ] installed operational testing passed
- [ ] certification binds to the **exact frozen artifact bytes**

## 12. Closing the release

- [ ] closure dossier assembled (see the campaign's dossier requirement)
- [ ] every item in this checklist either satisfied or explicitly recorded as an open decision
- [ ] **no item marked satisfied on the basis of file presence alone**

---

## Repair items referenced by this checklist

These are required by the gate and are not yet automated. They are listed so the gap is visible:

1. document-presence check script;
2. stale-version-reference check;
3. git-history secret scan;
4. packaged-VSIX and evidence secret scan;
5. dependency vulnerability scan;
6. SBOM generation;
7. build provenance generation;
8. artifact hash publication;
9. deletion/export behaviour test;
10. private/public memory boundary test;
11. automated `release_claims_gate`;
12. vulnerability/incident workflow test;
13. licence inventory automation;
14. accessibility audit;