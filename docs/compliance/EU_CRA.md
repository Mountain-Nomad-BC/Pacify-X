# EU Cyber Resilience Act (CRA)

Analysis against Regulation (EU) 2024/2847.

**PX does not claim CRA compliance or CRA exemption.** This document records the facts needed to
make the classification determination and **preserves that determination as an owner/legal
decision** rather than guessing it.

---

## 1. Why this matters now, not later

| Date | Milestone |
|---|---|
| 2024-12-10 | CRA entered into force |
| **2026-09-11** | **Manufacturer vulnerability and severe-incident reporting obligations began** |
| 2027-12-11 | Most other main obligations apply |

The reporting obligations are **already live** for an in-scope manufacturer. So classification is
no longer a "someday" item — but it is also not something a software project should decide by
assertion.

## 2. Open-source treatment

The European Commission's position: free/open-source software is **in CRA scope when it is made
available on the market in the course of a commercial activity**. Non-monetised free/open-source
software made available by its manufacturer is **not normally** a commercial activity for this
purpose.

The boundary therefore turns on commercial activity, and PX's *planned* paid services make that
boundary important.

**Do not assume "Apache-2.0 == CRA exempt."** A permissive licence is not a classification.

## 3. The classification question — OWNER_LEGAL_DECISION

Before commercial deployment or active EU distribution:

| # | Question | Status |
|---|---|---|
| Q1 | Is the PX core made available on the EU market in the course of a commercial activity? | **OPEN** |
| Q2 | Do paid adjacent services cause the core distribution to become part of a commercial activity? | **OPEN** |
| Q3 | Is the relevant actor a CRA "manufacturer"? | **OPEN** |
| Q4 | Could a future legal entity qualify as an "open-source software steward"? | **OPEN** |
| Q5 | Which exact binaries/products constitute the "product with digital elements"? | **OPEN** |

## 4. Facts available for that determination

Recorded so counsel has a stable basis (owner decision 2026-09-23):

| Fact | Value |
|---|---|
| Core licence | Apache-2.0, free |
| Core is a paid product | **no** |
| Donations | none currently characterised as a service relationship |
| Paid support | none |
| Hosted services | none |
| Managed routing | none |
| Team features | none |
| Accounts / billing | none |
| Commercial entity operating a hosted service | none |
| Distributed artifacts | source repository + VSIX |
| Locally-built artifacts | llama.cpp runtime (built by the operator, not distributed) |
| Model weights | not distributed |
| Pacify-X-operated endpoints | none |
| Remote telemetry | none |

**Owner intent (2026-09-23), recorded:** the 0.9.x core and extension are free, open-source
software under Apache-2.0; the core release is not a paid product; future optional commercial
services are possible and **must not silently change the classification of the core without a new
applicability review**.

## 5. What PX implements regardless of classification

Uncertainty about the legal classification must not prevent sensible CRA-aligned controls. PX
therefore maintains:

| CRA-aligned control | Where |
|---|---|
| Vulnerability intake channel | `SECURITY.md` |
| Vulnerability handling policy | `docs/security/VULNERABILITY_RESPONSE.md` |
| Severity ladder and triage | `docs/security/VULNERABILITY_RESPONSE.md` §3 |
| Actively-exploited-vulnerability detection/triage path | `docs/security/VULNERABILITY_RESPONSE.md` §2, §8 |
| Severe-incident definition and 24/72h/14d decision tree | `docs/security/VULNERABILITY_RESPONSE.md` §8 |
| Responsible security contact | `SECURITY.md` |
| Security update policy | `docs/security/SECURE_UPDATE_POLICY.md` |
| Supported lifetime / support period | `SECURITY.md`; `docs/security/SECURE_UPDATE_POLICY.md` §9 |
| Secure-by-default configuration | deny-by-default invariants |
| Dependency/update monitoring | `docs/security/SUPPLY_CHAIN.md` |
| Coordinated disclosure | `SECURITY.md` |
| Retained evidence demonstrating handling | `docs/security/INCIDENT_RESPONSE.md` §6 |
| SBOM policy | `docs/security/SBOM_POLICY.md` |
| Product inventory | `docs/compliance/COMPLIANCE_SCOPE.md` §4 |

**These are controls, not compliance.** Their presence is what makes a future reporting
obligation executable rather than improvised.

## 6. 2027 work (tracked, not yet applicable)

| Item | Status |
|---|---|
| conformity assessment | FUTURE (2027-12-11) |
| technical documentation | FUTURE |
| CE-marking determination | FUTURE |
| EU declaration of conformity | FUTURE |
| vulnerability-handling requirements | controls already maintained (§5) |
| security-by-design requirements | controls already maintained |
| user security instructions | `SECURITY.md` + this tree |
| support-period disclosure | `SECURITY.md` |
| post-market monitoring | FUTURE |
| importer/distributor obligations | FUTURE |

## 7. Reclassification triggers

Recorded in `policies/release-invariants.json`:

- commercial distribution, paid support, or a hosted service;
- marketing the free core together with a commercial offering;
- a legal entity beginning to act as manufacturer or steward;
- active EU distribution with a commercial relationship.

When any fires, this document and the [matrix](REGULATORY_APPLICABILITY_MATRIX.md) are re-opened
**before** the affected release.

## 8. Position statement

PX maintains CRA-aligned security and vulnerability controls **now**, because they are prudent
for any release. PX does **not** claim CRA compliance, and does **not** claim CRA exemption. The
manufacturer/commercial-activity determination is an **open owner/legal decision** (D1–D5).