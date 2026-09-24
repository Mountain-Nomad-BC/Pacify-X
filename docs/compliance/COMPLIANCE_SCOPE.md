# Compliance Scope

What this document tree is, what it is not, and how to read it.

---

## 1. What this is

A factual, evidence-based assessment of which security, privacy, and regulatory requirements
apply to Pacify-X 0.9.x, which do not, and which are reserved for a future decision.

## 2. What this is NOT

**This is not a compliance claim, and nothing here should be read as one.**

Specifically, Pacify-X does **not** claim to be:

- EU AI Act compliant;
- EU Cyber Resilience Act compliant;
- GDPR compliant;
- SOC 2 compliant;
- ISO 27001 certified;
- HIPAA compliant;
- FedRAMP compliant or authorised;
- FIPS compliant;
- NIST certified;
- "zero trust certified", "secure by design certified", or "enterprise compliant".

Where this tree describes **controls**, it describes controls — not certification. A control is
not a certification, and a document is not evidence.

## 3. The status vocabulary

Every requirement in the [applicability matrix](REGULATORY_APPLICABILITY_MATRIX.md) carries one
of:

| Status | Meaning |
|---|---|
| `APPLICABLE_NOW` | applies to the current release; control implemented or required |
| `APPLICABLE_HOSTED_ONLY` | applies only if hosted/commercial functionality is introduced |
| `APPLICABLE_JURISDICTION_OR_MODE` | applies only in a particular jurisdiction or deployment mode |
| `FUTURE_KNOWN_DATE` | applies from a known date or trigger |
| `OWNER_LEGAL_DECISION` | **a decision reserved for the owner or counsel** — not guessed here |
| `SATISFIED_VERIFIED` | already satisfied, **with evidence** |
| `NOT_APPLICABLE` | does not apply, **with a stated reason** |

`SATISFIED_VERIFIED` requires evidence. A document existing is not evidence that the behaviour
it describes is true. Where a claim rests on runtime behaviour, the evidence is a trace or a
machine-checked invariant.

## 4. The current factual position

Recorded so every downstream judgement has a stable basis:

| Fact | Value |
|---|---|
| Core licence | Apache-2.0 |
| Core is a paid product | no |
| Distribution | GitHub source + VS Code extension (VSIX) |
| PACIFY-X-operated endpoints | **none** |
| Remote telemetry | **none** |
| Automatic model download | **disabled** |
| Data reaching PACIFY-X-operated infrastructure | **none** |
| Model weights bundled | no |
| Hosted services offered | none |
| Accounts / billing | none |
| Primary audience | adult professional developers |
| High-risk/consequential use | unsupported and not certified |

Evidence for these: `.tmp/stage1/COMPLIANCE_WS1_RUNTIME_TRUTH.md` and
`policies/release-invariants.json` (machine-checked).

## 5. Reading order

1. [REGULATORY_APPLICABILITY_MATRIX.md](REGULATORY_APPLICABILITY_MATRIX.md) — the master matrix.
2. [EU_AI_ACT.md](EU_AI_ACT.md) — AI Act analysis, including Article 50 transparency.
3. [EU_CRA.md](EU_CRA.md) — Cyber Resilience Act analysis and the open classification question.
4. [GDPR.md](GDPR.md) — EEA privacy analysis.
5. [US_FEDERAL.md](US_FEDERAL.md) — FTC baseline and sector regimes.
6. [US_STATE_AI_PRIVACY_MATRIX.md](US_STATE_AI_PRIVACY_MATRIX.md) — state law tracking.
7. [ACCESSIBILITY.md](ACCESSIBILITY.md) — accessibility posture.
8. [EXPORT_CONTROL_REVIEW.md](EXPORT_CONTROL_REVIEW.md) — export/sanctions classification status.
9. [RELEASE_COMPLIANCE_CHECKLIST.md](RELEASE_COMPLIANCE_CHECKLIST.md) — the release gate.

## 6. Maintenance

Before every significant release, review this tree and update:

- the applicability matrix rows whose trigger may have fired;
- the dated future requirements;
- the status of any `OWNER_LEGAL_DECISION` item;
- the factual position in §4 if behaviour changed.

If behaviour changed and this tree did not, the tree is wrong — and the release compliance gate
is designed to catch the machine-checkable subset of that.

## 7. The rule this tree follows

> Do not claim legal compliance merely because a document or control exists.

That is why the matrix distinguishes *control present* from *obligation applies* from *verified*.