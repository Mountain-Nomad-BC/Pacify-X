# United States — Federal Baseline

There is no single horizontal U.S. private-sector AI statute. The practical baseline is FTC
consumer-protection authority plus sector-specific regimes.

**PX does not claim compliance with any federal framework.**

---

## 1. FTC — unfair or deceptive practices

The operative discipline is: **every public claim must be true and supported.** A claim that
overstates the product is the exposure — not the absence of a certification.

### Claims PX must not make (and does not make)

| Prohibited claim shape | Why | PX position |
|---|---|---|
| "private" when data can leave the machine | misleading if a configured provider is used | `PRIVACY.md` distinguishes local from provider-bound flows |
| "zero retention" unless the entire path is zero-retention | provider retention is not PX's behaviour to assert | `PROVIDER_DATA_HANDLING.md` requires the operator to confirm |
| "anonymous" if data can be linked to a user/device/account | PX does not collect, so it makes no anonymisation claim | no such claim |
| "secure" without qualification | unfalsifiable as stated | `DISCLAIMER.md` scopes security claims to evidence |
| "certified" beyond the exact certification scope | certification is scoped to a frozen artifact | `DISCLAIMER.md` states exactly what certification means |
| "deterministic" for model-generated behaviour | generation is probabilistic | `AI_LIMITATIONS.md` |
| "local" when cloud fallback can occur | silent fallback is prohibited by invariant | invariant `no-hidden-cloud-fallback` |
| "no training" unless every represented provider path supports it | a provider may train by default | `PROVIDER_DATA_HANDLING.md` requires confirmation |

### The release claim scan

A release test scans README, Marketplace text, onboarding text, docs, and UI strings for claims
that exceed the evidence — terms such as *secure*, *safe*, *private*, *anonymous*, *compliant*,
*certified*, *deterministic*, *guaranteed*, *zero retention*, *never*, *always*, and vendor
compliance acronyms.

**Status:** the *policy* is recorded here; the automated `release_claims_gate` is a **repair
item** in the compliance workstream. Until it exists, the manual rule is: every strong claim
points to evidence or it is rewritten.

## 2. Sector-specific regimes

PX should not claim compliance with specialised sectors unless separately validated. The base
product says **not validated for regulated-sector compliance by default**.

| Regime | Domain | PX position |
|---|---|---|
| HIPAA | healthcare / PHI | NOT_APPLICABLE — not validated, not intended for PHI |
| GLBA | financial institutions | NOT_APPLICABLE — not validated |
| FCRA | consumer reports | NOT_APPLICABLE — not validated; no consumer reporting |
| ECOA | lending / credit decisions | NOT_APPLICABLE — unsupported high-risk use |
| Employment law | hiring/firing/promotion | NOT_APPLICABLE — unsupported use |
| FERPA | education records | NOT_APPLICABLE — not validated, not intended for student records |
| COPPA | children under 13 | NOT_APPLICABLE — not child-directed (see §3) |
| Biometric laws (IL BIPA, TX CUBI, WA) | biometric identifiers | NOT_APPLICABLE — no biometric processing |
| Export controls (EAR/ITAR) | controlled technology | OWNER_LEGAL_DECISION — see `EXPORT_CONTROL_REVIEW.md` |
| Government contracting / FedRAMP | federal procurement | NOT_APPLICABLE — not authorised, not claimed |
| Controlled unclassified information (CUI) | CUI handling | NOT_APPLICABLE — not authorised for CUI |

## 3. Children's privacy (COPPA)

PX is positioned as a **developer/engineering tool**, not a child-oriented AI companion, and is
not directed at children. It is not marketed to minors.

Before any consumer-facing expansion: define a minimum age, determine COPPA applicability, assess
teen safety, add age-related data handling, and avoid emotional-dependence/companion claims unless
specifically reviewed. See also the Colorado and California items in
[US_STATE_AI_PRIVACY_MATRIX.md](US_STATE_AI_PRIVACY_MATRIX.md).

PX does not market itself as equivalent to a therapist, doctor, lawyer, financial adviser, or
other licensed professional.

## 4. State law

State AI and privacy law is now too active to treat as a footnote. See the dedicated document:
[US_STATE_AI_PRIVACY_MATRIX.md](US_STATE_AI_PRIVACY_MATRIX.md).

## 5. NIST guidance (voluntary)

PX maps its practices to NIST SSDF SP 800-218 and aligns with the AI RMF's risk framing. These
are **mappings, not certifications**, and no NIST certification is claimed. See
[SUPPLY_CHAIN.md](../security/SUPPLY_CHAIN.md) §7.

## 6. Position statement

PX is a developer tool with AI-assisted features. It makes no claim that exceeds its evidence,
is not validated for any regulated sector, is not directed at children, and states plainly that
compliance in a regulated deployment is the operator's responsibility. Export classification is
an **open owner/legal decision**.