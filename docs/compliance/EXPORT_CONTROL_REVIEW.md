# Export Control Review

**Status: OWNER_LEGAL_DECISION — not yet performed.**

This document records the analysis that must be completed before commercial international
distribution. It does **not** invent a restriction, and it does **not** claim that no restriction
applies. Both would be guesses.

---

## 1. Why an analysis is warranted

PX includes or touches:

- cryptography and security-adjacent tooling (signature verification, hashing, credential
  handling);
- software distribution tooling;
- model access and routing (local and remote);
- potentially advanced compute integrations (CUDA, hybrid CPU/GPU, MoE placement);
- a VS Code extension distributed through a public marketplace.

Each of those can be relevant to export classification in some jurisdictions.

## 2. Questions to answer — OWNER_LEGAL_DECISION

| # | Question | Status |
|---|---|---|
| E1 | Does any part of PX require an export classification or notification? | **OPEN** |
| E2 | Do encryption-software rules apply, and if so which category? | **OPEN** |
| E3 | Are restricted-party / sanctions screenings required for paid services? | **OPEN** |
| E4 | Are there country-availability restrictions for a hosted service? | **OPEN** (no hosted service exists) |
| E5 | Do provider terms prohibit certain jurisdictions? | **OPEN** — per-provider |

## 3. Facts available for that analysis

| Fact | Value |
|---|---|
| Distribution | public open-source repository + public VS Code Marketplace |
| Cryptography | PX uses standard libraries for hashing and signature verification; it does not implement novel cryptography |
| Key material | generated and held by the operator; PX is not a key-escrow or cryptographic service |
| Controlled technical data | none knowingly included |
| Weapons / defence applications | none; explicitly unsupported (see `HIGH_RISK_AND_CONSEQUENTIAL_USE.md`) |
| Sanctioned-party interactions | none; PX operates no service that interacts with parties |
| Hosted service | none |
| Data residency control | none needed — no PX hosting |

## 4. Deliberate position

PX **does not** add export-control boilerplate to the licence or README. Adding a restriction the
project cannot substantiate would be exactly the kind of unsupported claim the other documents in
this tree prohibit.

Instead the position is recorded here and surfaced as an open decision. If counsel determines a
classification or notification is required, this document is updated and the release process
incorporates it **before** distribution.

## 5. If you export on your own account

Open-source availability does not remove *your* obligations. If you are subject to export-control
rules, downloading and re-exporting this software may carry obligations independent of PX's
licence. That determination is yours.

## 6. Reclassification trigger

Recorded in `policies/release-invariants.json` and the
[matrix](REGULATORY_APPLICABILITY_MATRIX.md) §F as **D7**: any commercial international
distribution, paid service, or hosted service re-opens this analysis before the affected release.