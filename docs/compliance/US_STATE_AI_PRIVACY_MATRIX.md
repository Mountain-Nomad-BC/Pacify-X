# U.S. State AI and Privacy Law Matrix

State law is active enough that it must be tracked rather than footnoted. This matrix is
**reviewed before every major release**.

**PX does not claim compliance with any state statute.**

---

## 1. Tracking matrix

| State | Instrument | Effective | Applies to PX today? | Trigger | PX position |
|---|---|
| **Texas** | TRAIGA (Responsible AI Governance Act) | **2026-01-01** | likely not, as a developer tool | deploying AI in Texas; prohibited uses | see §2 |
| **Colorado** | ADMT law + Chatbot Safety Act | **2027-01-01** | not today | consequential decisions; consumer chatbot | see §3 |
| **California** | CCPA/CPRA + 2025 regulations (risk assessments, cybersecurity audits, ADMT) | **2026-01-01** | not today | commercial entity meeting thresholds + consumer PI | see §4 |
| **California** | AI Transparency Act (SB 942) | **2026-01-01** | not today | "covered provider": >1,000,000 monthly users, publicly accessible GenAI in CA | see §5 |
| **Illinois** | BIPA (biometric) | existing | no | biometric identifiers | not applicable — no biometric processing |
| **Washington / Texas** | biometric statutes | existing | no | biometric identifiers | not applicable |
| Others | state comprehensive privacy laws | rolling | not today | processing consumer PI at threshold | monitored |

This table is a **tracking device**. It is not exhaustive, and its rows change; re-verify each
before relying on it.

## 2. Texas — TRAIGA (effective 2026-01-01)

TRAIGA governs entities deploying AI in Texas and prohibits certain uses, including specified
manipulative uses, unlawful discrimination, certain social-scoring and government biometric uses,
and other prohibited conduct.

PX actions:

- [x] record a TRAIGA applicability row (**this row**);
- [x] the intended-use and high-risk documents do not permit explicitly prohibited uses
      ([HIGH_RISK_AND_CONSEQUENTIAL_USE.md](../../HIGH_RISK_AND_CONSEQUENTIAL_USE.md));
- [x] consequential-use workflows remain governable and auditable through authority gates;
- [x] documentation records that an **operator's** use can trigger obligations independent of
      PX's base licence.

**Status:** the boundary is documented. An Acceptable Use Policy that binds hosted-service users
is a **hosted-only** item and does not exist yet (no hosted service).

## 3. Colorado — ADMT + Chatbot Safety Act (effective 2027-01-01)

The Colorado AG describes requirements involving: disclosure that a conversational AI is AI and
not human; age estimation; protections for teen users; privacy/account controls for minors;
self-harm response protocols; restrictions on representing chatbot output as equivalent to
licensed professional services; and annual reporting.

PX is **not necessarily** a covered "conversational AI service" merely because it has a developer
assistant, but this must be evaluated before making PX broadly consumer-facing or marketing it to
minors.

PX actions:

- [ ] classify PX's conversational interface — **pending; recorded as an applicability item**
- [x] keep the developer-tool audience clear ([INTENDED_USE.md](../../INTENDED_USE.md));
- [x] do not market to children or minors without a dedicated child-safety review;
- [ ] monitor Colorado rulemaking through final rules;
- [ ] add a **January 2027 compliance checkpoint** — recorded below.

The AI-disclosure and "not a licensed professional" elements are already satisfied by
[AI_TRANSPARENCY.md](../../AI_TRANSPARENCY.md) and [US_FEDERAL.md](US_FEDERAL.md) §3.

## 4. California — CCPA/CPRA and ADMT regulations (2025 regs effective 2026-01-01)

The 2025 CCPA regulations include rules for risk assessments, cybersecurity audits for certain
businesses, automated decision-making technology, and consumer access/opt-out rights.

These do **not** automatically apply to every open-source developer. They become important when a
PX commercial entity meets CCPA applicability thresholds and processes California consumer
personal information.

Actions for any hosted/commercial PX service:

- [ ] CCPA applicability threshold review
- [ ] notice at collection
- [ ] privacy-policy disclosures
- [ ] consumer-rights workflow
- [ ] sale/sharing analysis
- [ ] Global Privacy Control handling if applicable
- [ ] service-provider/contractor agreements
- [ ] ADMT applicability
- [ ] risk-assessment requirements
- [ ] cybersecurity-audit applicability

**Status:** NOT_APPLICABLE today — there is no commercial entity, no accounts, and no processing
of consumer personal information. Recorded as hosted-only work.

## 5. California — AI Transparency Act / SB 942 (operative 2026-01-01)

Applies to a defined "covered provider" of a generative AI system with **more than 1,000,000
monthly visitors/users** that is publicly accessible in California, with requirements around
detection/provenance and disclosures for generated image/video/audio content.

PX is unlikely to meet that trigger as a developer framework, but the thresholds are recorded so
compliance is not a late rewrite:

| Milestone | Action |
|---|---|
| 250k monthly users | reassess applicability |
| 500k monthly users | reassess applicability |
| before 1M monthly users | **mandatory counsel review** |
| any time | preserve content-provenance architecture so marking is possible if required |

**Status:** NOT_APPLICABLE today. Content-provenance capability is preserved in the architecture
(see [AI_TRANSPARENCY.md](../../AI_TRANSPARENCY.md) §6) so that a future trigger does not require
re-architecting.

## 6. Review checkpoints

| Date | Action |
|---|---|
| 2026-01-01 | Texas TRAIGA + California statutes operative — confirm no change to PX's position |
| 2027-01-01 | Colorado ADMT + Chatbot Safety Act operative — re-run §3 |
| before any hosted service | run §4 in full |
| 250k / 500k / 1M monthly users | run §5 in full |
| every major release | review this matrix |

## 7. Position statement

PX is a developer tool. It does not process consumer personal information, has no commercial
entity, no accounts, and no hosted service, so state consumer-privacy statutes do not currently
attach to it. It documents the operator's independent obligations, keeps its developer-tool
audience clear, and tracks the dates at which that could change.