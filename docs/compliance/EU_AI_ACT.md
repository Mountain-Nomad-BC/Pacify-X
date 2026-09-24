# EU AI Act

Analysis against Regulation (EU) 2024/1689. **No compliance is claimed.** This records
applicability and the decisions reserved for the owner or counsel.

---

## 1. Timing that matters

| Date | Milestone | Applies to PX? |
|---|---|---|
| 2024-08-01 | AI Act entered into force | — |
| 2025-02-02 | Prohibited practices + AI literacy | not applicable if no prohibited practice is offered |
| 2025-08-02 | GPAI model provider obligations | **no** — PX is not a GPAI provider (§2) |
| **2026-08-02** | **Article 50 transparency obligations** | **potentially applicable** (§4) |
| 2027-08-02 | broader high-risk obligations | only if a high-risk purpose is intended — unsupported |

## 2. PX is not a GPAI model provider

PX does not:

- train a general-purpose model;
- substantially modify and release one under its own name as provider;
- place its own GPAI model on the EU market.

PX loads GGUF models, routes requests, calls provider APIs, invokes a local runtime, performs
retrieval, and wraps models behind a common interface. None of that makes PX the *provider* of a
general-purpose model.

**Classification:** GPAI provider obligations — **NOT_APPLICABLE** to the 0.9.x core.

**Reclassification trigger:** PX training a general-purpose model, substantially modifying and
releasing one under the PX name where the law treats PX as provider, or placing its own GPAI
model on the EU market.

## 3. PX can still be an "AI system"

> Do not rely on "we do not ship weights" as a complete exemption.

PX exposes AI behaviour under the PX product and generates/infers outputs through connected
models. So PX may be an AI system, and the *role* matters.

### Legal role per feature — OWNER_LEGAL_DECISION

| Feature | Candidate role | Status |
|---|---|---|
| PX core as a developer tool | likely deployer-tooling, or neither | **OPEN — counsel** |
| A future hosted PX service | provider or deployer | **OPEN — depends on service design** |
| A PX-brokered third-party model | provider of a downstream system vs intermediary | **OPEN — counsel** |

**Recorded as D6 in the [applicability matrix](REGULATORY_APPLICABILITY_MATRIX.md) §F.** Not guessed.

### Engineering posture PX maintains regardless

- intended-purpose documentation — [INTENDED_USE.md](../../INTENDED_USE.md);
- model/runtime/provider identity — receipts and the model registry;
- AI interaction disclosure — [AI_TRANSPARENCY.md](../../AI_TRANSPARENCY.md);
- human oversight and tool-execution controls — authority gates, approvals;
- logs/evidence appropriate to the use — receipts and the evidence tree;
- prevention of silently-enabled high-risk purpose — the unsupported-use list and release claim
  scan (per-plugin gate is a repair item);
- operator documentation — this tree.

## 4. Article 50 — transparency (applies 2026-08-02)

PX adopts the safest useful baseline:

| Requirement | PX position | Status |
|---|---|---|
| Disclose that the user interacts with AI | console discloses AI involvement; model/route shown | **implemented** |
| Model/provider identity available to the user | receipts record model, runtime, provider | **implemented** |
| Distinguish AI suggestions from deterministic actions | tool authority outside the model; approvals required | **implemented** |
| Label AI-generated or AI-modified synthetic content where applicable | PX generates no media content; marking capability preserved for future generators | **NOT_APPLICABLE today** (no media generation) |
| Machine-readable provenance/marking capability for generators | capability preserved in the architecture | **NOT_APPLICABLE today** |
| Do not claim unmarked output is human-created | stated in `AI_TRANSPARENCY.md` §6 | **implemented** |

Where PX merely **brokers** a third-party generator, marking obligations sit with that generator,
and PX documents the split rather than implying it guarantees the upstream behaviour.

## 5. High-risk AI (Annex III)

PX is positioned as a **general AI engineering framework**, not an application intended to make
legally consequential decisions.

**Do not market the base product as intended for high-risk Annex III functions** unless the
high-risk compliance stack is deliberately implemented. The unsupported-use list is in
[HIGH_RISK_AND_CONSEQUENTIAL_USE.md](../../HIGH_RISK_AND_CONSEQUENTIAL_USE.md).

### Release tests that should exist

- [ ] default docs do not advertise hiring, lending, admissions, insurance, healthcare,
      biometric, law-enforcement, or benefits decision-making;
- [ ] example workflows do not accidentally convert those functions into intended uses;
- [ ] plugins declaring consequential-decision capability are classified and gated;
- [ ] users see an unsupported/high-risk-use warning before enabling such a workflow.

**Status:** the first two are covered by the release claim scan; the last two require the
per-plugin gate, which is a **repair item**.

## 6. AI literacy

Article 4 AI-literacy expectations are addressed by documentation for operators:
[INTENDED_USE.md](../../INTENDED_USE.md), [AI_LIMITATIONS.md](../../AI_LIMITATIONS.md), and this
tree. Organisations deploying PX should ensure their users understand the system's limits.

## 7. Position statement

PX is a developer tool that includes AI-assisted features. It discloses AI involvement, exposes
model identity, gates tool execution, and documents intended use and limitations. It does **not**
claim AI Act compliance, is **not** positioned for high-risk purposes, and defers the legal-role
determination to counsel.

Applicability is reassessed through the [matrix](REGULATORY_APPLICABILITY_MATRIX.md) §G triggers.