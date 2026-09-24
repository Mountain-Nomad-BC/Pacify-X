# Regulatory Applicability Matrix

The master assessment: every requirement, its applicability, its trigger, the Pacify-X control,
where it is implemented, its validation evidence, its status, and any decision reserved for the
owner.

**No compliance is claimed.** `SATISFIED_VERIFIED` means *the stated control is present and its
evidence was checked* — not that a regulation has been satisfied, and not that a certification
exists.

Status vocabulary: see [COMPLIANCE_SCOPE.md](COMPLIANCE_SCOPE.md) §3.

---

## A. Security and supply chain

| Requirement | Applicability | Trigger | Pacify-X control | Implementation | Validation evidence | Status |
|---|---|---|
| Vulnerability reporting channel | APPLICABLE_NOW | any release | private intake + triage process | `SECURITY.md`, `docs/security/VULNERABILITY_RESPONSE.md` | document present; contact published | SATISFIED_VERIFIED |
| Security update policy | APPLICABLE_NOW | any release | checksum verification, revocation, rotation | `docs/security/SECURE_UPDATE_POLICY.md`; `extension/Install-PacifyX.ps1` | installer refuses on checksum mismatch | SATISFIED_VERIFIED |
| Threat model | APPLICABLE_NOW | any release | declared trust boundaries B1–B11 | `docs/security/THREAT_MODEL.md` | document present | SATISFIED_VERIFIED |
| Security architecture | APPLICABLE_NOW | any release | authority gates, least privilege, contained execution | `docs/security/SECURITY_ARCHITECTURE.md` | document present | SATISFIED_VERIFIED |
| Incident response | APPLICABLE_NOW | any release | incident classes + sequence | `docs/security/INCIDENT_RESPONSE.md` | document present | SATISFIED_VERIFIED |
| Secret scanning (tree) | APPLICABLE_NOW | every release | invariant `no-shipped-secrets` | `scripts/verify_release_invariants.py` | **machine-checked: PASS (0 findings)** | SATISFIED_VERIFIED |
| Secret scanning (git history) | APPLICABLE_NOW | every release | history scan | — | **not yet run** | APPLICABLE_NOW (repair item) |
| Secret scanning (VSIX / evidence) | APPLICABLE_NOW | every release | packaged-artifact scan | — | **not yet run** | APPLICABLE_NOW (repair item) |
| Endpoint inventory | APPLICABLE_NOW | every release | invariant `no-px-operated-remote-endpoints` | `scripts/verify_release_invariants.py` | **machine-checked: PASS** | SATISFIED_VERIFIED |
| SBOM | APPLICABLE_NOW | every release | policy + gate declared | `docs/security/SBOM_POLICY.md` | policy present; **generator is a repair item** | APPLICABLE_NOW (repair item) |
| Build provenance | APPLICABLE_NOW | every release | source commit, toolchain, hashes | `docs/security/SUPPLY_CHAIN.md` | declared; generation is a repair item | APPLICABLE_NOW (repair item) |
| Dependency vulnerability scan | APPLICABLE_NOW | every release | pinned deps, scan at release | `docs/security/SUPPLY_CHAIN.md` | **not yet automated** | APPLICABLE_NOW (repair item) |
| Licence inventory | APPLICABLE_NOW | every release | third-party + model registries | `THIRD_PARTY_NOTICES.md`, `MODEL_AND_DATA_LICENSES.md` | documents present; automation is a repair item | SATISFIED_VERIFIED (documents) |
| Fail-closed design | APPLICABLE_NOW | every release | deny-by-default; no hidden fallback | invariants `no-hidden-cloud-fallback`, `explicit-provider-use-only` | **machine-checked: PASS** | SATISFIED_VERIFIED |
| Plugin/tool permission controls | APPLICABLE_NOW | if plugins ship | manifest + deny-by-default + grants | `docs/security/SECURITY_ARCHITECTURE.md` §8 | **full manifest schema incomplete** | APPLICABLE_NOW (repair item) |

## B. Privacy and data

| Requirement | Applicability | Trigger | Pacify-X control | Implementation | Validation evidence | Status |
|---|---|---|
| Privacy disclosure | APPLICABLE_NOW | any distribution | describes actual behaviour | `PRIVACY.md` | matches WS-1 runtime truth | SATISFIED_VERIFIED |
| Data-flow inventory | APPLICABLE_NOW | any distribution | categories, boundaries, destinations | `DATA_FLOW.md` | matches WS-1 static scan | SATISFIED_VERIFIED |
| Telemetry disclosure | APPLICABLE_NOW | any distribution | states none is emitted, defines future policy | `TELEMETRY.md` | invariant + extension guard **PASS** | SATISFIED_VERIFIED |
| Retention/deletion semantics | APPLICABLE_NOW | any distribution | defaults + append-only exception | `DATA_RETENTION_AND_DELETION.md` | document present | SATISFIED_VERIFIED |
| Memory privacy boundary | APPLICABLE_NOW | if memory enabled | scopes never merged; deletion complete | `MEMORY_PRIVACY_MODEL.md` | document present; runtime tests | SATISFIED_VERIFIED |
| Provider data handling | APPLICABLE_NOW | if providers configured | denied by default; per-provider facts listed | `PROVIDER_DATA_HANDLING.md` | document present | SATISFIED_VERIFIED |
| Live-session egress proof | APPLICABLE_NOW | every release | prove no outbound socket | — | **not yet traced** | APPLICABLE_NOW (adversarial audit) |
| GDPR controller/processor | OWNER_LEGAL_DECISION | EEA personal data | — | `GDPR.md` | no PX processing of EEA personal data today | OWNER_LEGAL_DECISION |
| GDPR DSAR workflow | APPLICABLE_HOSTED_ONLY | hosted service | — | `GDPR.md` | n/a — no accounts | NOT_APPLICABLE (local-only) |
| CCPA/CPRA thresholds | APPLICABLE_HOSTED_ONLY | commercial entity + thresholds | — | `US_STATE_AI_PRIVACY_MATRIX.md` | n/a today | NOT_APPLICABLE (no commercial entity) |
| Children's data (COPPA) | APPLICABLE_JURISDICTION_OR_MODE | child-facing use | developer-tool positioning; not marketed to minors | `INTENDED_USE.md`, `US_FEDERAL.md` | not child-directed | NOT_APPLICABLE (not child-directed) |

## C. AI-specific

| Requirement | Applicability | Trigger | Pacify-X control | Implementation | Validation evidence | Status |
|---|---|---|
| AI interaction disclosure | APPLICABLE_NOW | any AI feature | UI discloses AI + active model/route | `AI_TRANSPARENCY.md` | `AI_TRANSPARENCY.md`; console model indicator | SATISFIED_VERIFIED |
| Model/provider identity inspectable | APPLICABLE_NOW | any AI feature | receipts record model + runtime | `AI_TRANSPARENCY.md` §4 | gateways emit exact receipts | SATISFIED_VERIFIED |
| Tool execution separated from generation | APPLICABLE_NOW | any tool use | ToolBroker + authority gates | `docs/security/SECURITY_ARCHITECTURE.md` | architecture present; tests | SATISFIED_VERIFIED |
| AI Act Art. 50 transparency | FUTURE_KNOWN_DATE (2026-08-02) | placing an AI system on the EU market | disclosure + identity + provenance capability | `EU_AI_ACT.md` | disclosure implemented; **legal role per feature is an OWNER_LEGAL_DECISION** | FUTURE_KNOWN_DATE |
| GPAI model provider obligations | NOT_APPLICABLE | providing a GPAI model | PX ships no weights and trains none | `EU_AI_ACT.md` §2 | `MODEL_AND_DATA_LICENSES.md`; no weights bundled | NOT_APPLICABLE (not a GPAI provider) |
| High-risk AI (Annex III) | NOT_APPLICABLE + gate | intending a high-risk purpose | unsupported use list + release claim scan | `HIGH_RISK_AND_CONSEQUENTIAL_USE.md` | documented boundary; per-plugin gate is a repair item | APPLICABLE_NOW (gate repair item) |
| Generated-content marking | APPLICABLE_JURISDICTION_OR_MODE | if PX controls image/audio/video generation | provenance capability preserved | `AI_TRANSPARENCY.md` §6 | PX does not currently generate media | NOT_APPLICABLE (no media generation) |
| AI literacy / operator docs | APPLICABLE_NOW | any AI feature | intended-use + limitations docs | `INTENDED_USE.md`, `AI_LIMITATIONS.md` | documents present | SATISFIED_VERIFIED |

## D. Regulatory frameworks

| Requirement | Applicability | Trigger | Pacify-X control | Implementation | Validation evidence | Status |
|---|---|---|
| **EU CRA — classification** | **OWNER_LEGAL_DECISION** | "made available on the market in the course of a commercial activity" | facts recorded; controls built regardless | `EU_CRA.md` | §4 factual position in `COMPLIANCE_SCOPE.md` | **OWNER_LEGAL_DECISION** |
| CRA — vulnerability handling | APPLICABLE_NOW (aligned, regardless of classification) | prudent release | intake, triage, severity, regression, advisory, revocation | `docs/security/VULNERABILITY_RESPONSE.md` | process present | SATISFIED_VERIFIED (controls) |
| CRA — severe incident reporting (24/72h/14d) | FUTURE_KNOWN_DATE (2026-09-11 if manufacturer) | CRA manufacturer status | decision tree documented | `VULNERABILITY_RESPONSE.md` §8 | depends on the classification above | OWNER_LEGAL_DECISION |
| CRA — 2027 obligations | FUTURE_KNOWN_DATE (2027-12-11) | full application | tracked epic | `EU_CRA.md` | recorded | FUTURE_KNOWN_DATE |
| CRA — SBOM / secure-by-default | APPLICABLE_NOW (aligned) | prudent release | SBOM policy; deny-by-default | `SBOM_POLICY.md`; invariants | policy + invariants PASS | SATISFIED_VERIFIED (controls) |
| AI Act — legal role per feature | OWNER_LEGAL_DECISION | EU placement | roles recorded, not assumed | `EU_AI_ACT.md` §3 | — | OWNER_LEGAL_DECISION |
| Export control / sanctions classification | OWNER_LEGAL_DECISION | commercial international distribution | analysis checklist | `EXPORT_CONTROL_REVIEW.md` | not yet performed | OWNER_LEGAL_DECISION |
| Accessibility | APPLICABLE_NOW (good practice) | any UI | keyboard, labels, contrast, focus | `ACCESSIBILITY.md` | posture documented; audit is a repair item | APPLICABLE_NOW (audit) |
| Sector regimes (HIPAA, GLBA, FCRA, ECOA, FERPA) | NOT_APPLICABLE | regulated deployment | explicitly not validated | `US_FEDERAL.md` | `INTENDED_USE.md` states not validated | NOT_APPLICABLE (not validated) |
| SOC 2 / ISO 27001 / FedRAMP / FIPS | NOT_APPLICABLE | enterprise procurement | not claimed | `DISCLAIMER.md` | `not_claimed` list in `policies/release-invariants.json` | NOT_APPLICABLE (not claimed) |

## E. Conditional — hosted / commercial (do not implement until the trigger fires)

| Requirement | Applicability | Trigger | Status |
|---|---|
| Terms of Service | APPLICABLE_HOSTED_ONLY | hosted/paid service | NOT_APPLICABLE (placeholder only) |
| Acceptable Use Policy | APPLICABLE_HOSTED_ONLY | hosted/paid service | NOT_APPLICABLE (placeholder only) |
| Hosted privacy policy | APPLICABLE_HOSTED_ONLY | hosted service | NOT_APPLICABLE (placeholder only) |
| Data Processing Addendum | APPLICABLE_HOSTED_ONLY | business customers | NOT_APPLICABLE (placeholder only) |
| Subprocessor list | APPLICABLE_HOSTED_ONLY | hosted service | NOT_APPLICABLE (placeholder only) |
| SLA | APPLICABLE_HOSTED_ONLY | offered SLA | NOT_APPLICABLE (not offered) |
| Billing / refunds | APPLICABLE_HOSTED_ONLY | paid service | NOT_APPLICABLE (no paid service) |
| Account deletion policy | APPLICABLE_HOSTED_ONLY | accounts | NOT_APPLICABLE (no accounts) |
| SCC / transfer mechanism | APPLICABLE_HOSTED_ONLY | EEA personal data + transfer | NOT_APPLICABLE (no PX processing) |
| DMCA / copyright process | APPLICABLE_HOSTED_ONLY | hosting user public content | NOT_APPLICABLE (hosts none) |
| DSAR process | APPLICABLE_HOSTED_ONLY | accounts + personal data | NOT_APPLICABLE (no accounts) |

**These are recorded so a future service is classified independently rather than forcing the core
architecture to be redesigned.** They are not created as documents, because inventing Terms for a
service that does not exist is a false statement about the product.

## F. Decision register

Decisions reserved for the owner or counsel. Nothing here is guessed.

| # | Decision | Status | Facts available |
|---|---|
| D1 | Is the PX core made available on the EU market in the course of a commercial activity? | **OPEN** | core is free Apache-2.0, not a paid product; no commercial relationship in 0.9.x |
| D2 | Do future paid services make the core distribution part of a commercial activity? | **OPEN** | deferred to the future trigger |
| D3 | Is the relevant actor a CRA "manufacturer"? | **OPEN** | depends on D1 |
| D4 | Could a future entity qualify as an "open-source software steward"? | **OPEN** | depends on D1/D3 |
| D5 | Which exact binaries constitute the "product with digital elements"? | **OPEN** | source, VSIX, locally-built runtime are distinct artifacts |
| D6 | PX's legal role per AI Act feature (provider/deployer/importer/distributor/neither) | **OPEN** | PX ships no weights; exposes AI behaviour under its own product |
| D7 | Export classification / sanctions screening requirement | **OPEN** | contains crypto-adjacent tooling; not yet analysed |
| D8 | GDP controller/processor characterisation if EEA personal data ever arrives | **OPEN** | no PX processing today |

## G. Maintenance triggers

Re-open this matrix when any of these occur:

- a PX-operated endpoint or hosted service is introduced;
- production telemetry is introduced;
- accounts, billing, or teams are introduced;
- commercial distribution or paid support begins;
- a high-risk/consequential use is proposed;
- PX begins training or distributing model weights;
- a new jurisdiction is targeted;
- an applicable regulation's effective date arrives;
- user scale changes materially (reassess at 250k / 500k monthly users; mandatory counsel review
  before 1M, per the California AI Transparency Act trigger).

Each is also recorded as a reclassification trigger in `policies/release-invariants.json`.