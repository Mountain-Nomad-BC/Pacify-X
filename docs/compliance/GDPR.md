# GDPR / EEA Privacy

Analysis of the General Data Protection Regulation position.

**PX does not claim GDPR compliance.** This document records the factual position and the
decisions reserved for the owner or counsel.

---

## 1. Local-only mode — the publisher's exposure is substantially smaller

If PX processes data only on the user's machine, under the user's control, and sends nothing to a
PX-operated service, then the PX publisher is not receiving EEA personal data through PX.

**Verified facts (owner decision 2026-09-23):**

| Fact | Value |
|---|---|
| Pacify-X-operated infrastructure | **none** |
| Data reaching PX-operated infrastructure | **none** |
| PACIFY-X-operated endpoints in code | **none** (machine-checked) |
| Remote telemetry | **none** (machine-checked) |
| Accounts / user records | none |
| Billing records | none |
| Support uploads | none |
| Hosted logs | none |
| Hosted memory | none |
| Cloud sync | none |

The publisher therefore does **not** operate a processing activity over user data in the 0.9.x
core. That is a factual statement about the architecture, not a compliance conclusion.

## 2. External providers — a separate controller boundary

When a user configures an external provider, the user sends their own content to a third party:

- the user chooses the provider;
- the user supplies the credential;
- the provider's terms govern retention and training;
- the provider is the recipient, not Pacify-X.

PX's role in that flow is the tool that made the user's instruction possible. Characterising who
is controller and who is processor in that specific relationship is **D8 — OWNER_LEGAL_DECISION**,
and it depends on the deployment.

PX reduces ambiguity where it can:

- providers are denied by default;
- no hidden fallback to a provider;
- the routing decision is inspectable;
- credentials live in OS credential storage, not in the repository.

## 3. Memory — the place personal data would accumulate

Persistent memory is the feature most likely to turn technical interaction into a long-lived
personal-data store. PX treats it accordingly:

| Expectation | PX control |
|---|---|
| Memory explicitly documented | [MEMORY_PRIVACY_MODEL.md](../../MEMORY_PRIVACY_MODEL.md) |
| Local vs hosted visually distinguishable | local-only in 0.9.x |
| Private/public promotion requires explicit policy | declassification gate for knowledge promotion |
| Deletion leaves no retrievable remnants | deletion must clear vector/lexical/graph/index projections |
| Backups and immutable provenance have documented semantics | [DATA_RETENTION_AND_DELETION.md](../../DATA_RETENTION_AND_DELETION.md) |
| One project's memory does not leak to another | project-scoped custody, hard boundary |
| Plugin and model access capability-bound | capability grants, no inherited authority |

## 4. What would trigger GDPR obligations

GDPR analysis becomes necessary when PX or an affiliated service receives EEA personal data —
through hosted memory, centralised telemetry, crash reports, accounts, billing, support uploads,
team workspaces, hosted logs, or cloud synchronisation. **None of these exist in 0.9.x.**

## 5. Pre-conditions before any such service ships

| Item | Status |
|---|---|
| identify controller vs processor role | OWNER_LEGAL_DECISION (D8) |
| lawful basis per processing purpose | not applicable — no processing |
| privacy notice | hosted-only placeholder |
| data minimisation | design requirement for the service |
| purpose limitation | design requirement |
| retention schedule | hosted-only |
| access/correction/deletion/export | hosted-only |
| security measures | controls in `docs/security/` |
| processor agreements | hosted-only |
| subprocessors | hosted-only |
| international-transfer mechanism | hosted-only |
| SCCs where required | hosted-only |
| DPIA trigger evaluation | hosted-only |
| breach response | `docs/security/INCIDENT_RESPONSE.md` |
| DPO requirement evaluation | hosted-only |
| records of processing | hosted-only |

**These are not created as documents now**, because publishing a privacy policy or a DPA for a
service that does not exist would misstate the product. They are recorded as triggers.

## 6. Data subject rights in the current model

Because the data is on the user's own machine, data subject rights are exercised locally:

| Right | How it works in 0.9.x |
|---|---|
| Access | inspect the local custody store; memory is exportable |
| Rectification | edit or supersede memory and knowledge |
| Erasure | delete the item or the project store; deletion must clear all projections |
| Portability | export memory and knowledge |
| Objection / restriction | disable memory or knowledge features |

There is no PX-operated system holding the data, so there is no PX-side request queue. If a hosted
service is ever introduced, a DSAR process becomes required **before** it ships.

## 7. International transfers

No transfer mechanism is required today because PX does not transfer personal data to
PX-operated infrastructure. A user sending data to a provider they chose is making their own
transfer decision, governed by that provider's terms.

## 8. Position statement

PX processes nothing on PX-operated infrastructure. The publisher therefore does not operate a
processing activity over EEA personal data in the 0.9.x core. PX does **not** claim GDPR
compliance, and the controller/processor characterisation for provider-bound flows is an **open
owner/legal decision** (D8).