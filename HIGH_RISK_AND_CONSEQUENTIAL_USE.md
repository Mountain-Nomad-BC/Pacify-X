# High-Risk and Consequential Use

PACIFY-X is a general AI engineering framework. It is **not** an application intended to make
legally consequential decisions about people, and it is not certified for such use.

This document defines the boundary, explains why it exists, and describes the architectural gate
that keeps the boundary from eroding silently.

---

## 1. Unsupported by default

PACIFY-X is unsupported and unauthorised for use as, or as a component of, decision-making in:

| Domain | Examples of unsupported use |
|---|---|
| Employment | screening, ranking, hiring, firing, promotion, performance evaluation |
| Education | admissions, grading, proctoring, student risk scoring |
| Credit and lending | creditworthiness, loan approval, limit setting |
| Insurance | eligibility, underwriting, pricing, claims decisions |
| Healthcare | diagnosis, treatment recommendation, triage, clinical decision support |
| Legal | legal advice, case outcome prediction, sentencing support |
| Government benefits | eligibility determination, fraud scoring, benefit administration |
| Law enforcement | suspect identification, risk scoring, predictive policing |
| Biometrics | identification, verification, emotion inference, categorisation of people |
| Critical infrastructure | control of power, water, transport, or communications systems |
| Safety-critical control | physical systems where failure can cause harm |
| Autonomous weapons | any weapons or armed-conflict application |

Any other use that law defines as high-risk or consequential about a natural person falls in the
same category.

## 2. Why this boundary exists

Two reasons, neither of them marketing:

1. **The compliance stack does not exist.** High-risk use in these domains carries obligations —
   conformity assessment, risk management, human oversight design, record-keeping, accuracy
   testing, registration, post-market monitoring — that PACIFY-X has not implemented and does
   not claim.
2. **The failure modes are unacceptable there.** PACIFY-X is probabilistic software. In these
   domains, errors fall on people, and the consequences are not reversible by a rollback.

## 3. The architecture gate

The boundary must not erode through a plugin, a workflow, or an example. The intended controls:

- **Documentation gate** — default documentation, examples, and sample workflows must not
  advertise consequential-decision use. A release test scans the docs and examples for
  high-risk intended-use drift.
- **Capability classification** — a plugin or integration that declares consequential-decision
  capability must be classified, and that classification is part of the plugin manifest.
- **Gating** — such a capability is denied by default and requires an explicit operator
  acknowledgement that names the domain and the unsupported status before it can be enabled.
- **Evidence** — enabling it is recorded, with the operator, the time, and the acknowledged
  boundary.

**Current status of that gate:** the boundary is documented and enforced at the release level
(docs, examples, and claim scanning). The per-plugin classification and acknowledgement gate for
consequential-decision capabilities is **not yet implemented** and is recorded as a repair item
for the current campaign. Until it exists, the correct control is that no such capability is
shipped.

## 4. If you believe you have a legitimate high-risk use

That is a conversation, not a configuration flag. It requires:

- the specific domain and the applicable legal regime;
- the compliance stack that regime requires;
- validation evidence appropriate to that domain;
- a deliberate decision to support it, recorded in
  `docs/compliance/REGULATORY_APPLICABILITY_MATRIX.md`.

It is not something to be enabled by editing a file.

## 5. Operator responsibility

An operator who uses PACIFY-X in a consequential domain assumes obligations that PACIFY-X's
open-source licence does not discharge — including, in many jurisdictions, obligations that
attach to the *deployer* regardless of the software's licence. PACIFY-X's permissive licence is
not a compliance authorisation.

---

See also: [INTENDED_USE.md](INTENDED_USE.md), [AI_LIMITATIONS.md](AI_LIMITATIONS.md),
[docs/compliance/EU_AI_ACT.md](docs/compliance/EU_AI_ACT.md).