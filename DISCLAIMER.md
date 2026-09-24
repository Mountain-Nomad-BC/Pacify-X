# Disclaimer

## Software

PACIFY-X is provided under the Apache License 2.0, **without warranties or conditions of any
kind**, express or implied, including warranties of merchantability, fitness for a particular
purpose, or non-infringement. See [LICENSE](LICENSE).

## AI output

- AI can generate **incorrect** output. It can be wrong confidently and plausibly.
- PACIFY-X can **invoke tools and perform mutations** when authorised. Those effects are real.
- **You remain responsible** for reviewing actions and their consequences in your context.
- Generated code, commands, and configurations should be reviewed before you rely on them.

## What certification means — and does not mean

When PACIFY-X says a release is "certified", it means exactly this:

> The **exact frozen artifact** passed the **included validation profile** — its governed section
> gates, full test profile, repository validation, package and install checks, and installed
> operational testing — and the evidence binds to those exact bytes.

It does **not** mean:

- the software is bug-free;
- the software is secure under all conditions;
- the software is legally compliant for your use;
- the software is safe for any particular regulated use;
- the software has been independently audited, penetration-tested, or accredited.

PACIFY-X certification is **self-certification**. It is evidence about a specific artifact, not a
third-party assessment of it.

## Compliance statements

PACIFY-X does **not** claim to be:

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

Where PACIFY-X describes controls, it describes *controls*, not a certification. Applicability
and compliance depend on your deployment context, the providers you enable, your data flows, and
your intended use.

## Third-party software and models

- PACIFY-X redistributes third-party components under their own licences; see
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- PACIFY-X does **not** bundle model weights. Models you use are governed by their own licences
  and acceptable-use policies; see [MODEL_AND_DATA_LICENSES.md](MODEL_AND_DATA_LICENSES.md).
- The Apache-2.0 licence of PACIFY-X does not extend to third-party model weights, providers, or
  services.

## External services

If you configure an external model provider, your use of that provider is governed by **their**
terms, not by this project. Costs, availability, retention, and training behaviour are theirs.

## Your responsibility as operator

You are responsible for:

- the use you make of the software and its outputs;
- the data you process with it;
- the providers you configure and authorise;
- compliance obligations that attach to *you* as a deployer in your jurisdiction, regardless of
  this project's licence;
- the security of the machine it runs on.

---

See also: [INTENDED_USE.md](INTENDED_USE.md), [AI_LIMITATIONS.md](AI_LIMITATIONS.md),
[HIGH_RISK_AND_CONSEQUENTIAL_USE.md](HIGH_RISK_AND_CONSEQUENTIAL_USE.md),
[docs/compliance/COMPLIANCE_SCOPE.md](docs/compliance/COMPLIANCE_SCOPE.md).