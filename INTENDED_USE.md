# Intended Use

## What PACIFY-X is intended for

PACIFY-X is an engineering and AI-operations framework for **software development work**. Its
intended purposes are:

| Purpose | Description |
|---|---|
| Software engineering | understanding, modifying, testing, and documenting software projects |
| AI engineering | configuring, routing, evaluating, and governing models and providers |
| Orchestration | composing governed workflows, agents, and scheduled maintenance |
| Retrieval | searching your own project, knowledge, and memory through governed interfaces |
| Governed tool execution | running tools and effects through authority, permission, and approval gates |
| Model and runtime management | discovering, admitting, and operating local model runtimes |
| Diagnostics | inspecting the system's own health, evidence, and failure behaviour |
| Knowledge and memory management | curating project knowledge and persistent memory under policy |

## Who it is for

Developers, engineering teams, and operators who are comfortable running tooling on their own
machines and who will review what the system does before trusting it.

It is a **developer tool**. It assumes the user is an adult professional working in a
development context.

## What PACIFY-X is NOT certified for

By default, PACIFY-X is **not validated, certified, or intended** for:

- employment, hiring, firing, promotion, or workforce decisions;
- education admissions, grading, or student evaluation;
- credit, lending, or financial eligibility decisions;
- insurance eligibility or pricing;
- medical diagnosis, treatment, or clinical decision support;
- legal determinations or legal advice;
- government benefits eligibility or administration;
- law enforcement or criminal justice decisions;
- biometric identification or categorisation;
- critical infrastructure control;
- safety-critical physical control systems;
- autonomous weapons or use in armed conflict;
- any other use that law defines as a consequential or high-risk decision about a person.

See [HIGH_RISK_AND_CONSEQUENTIAL_USE.md](HIGH_RISK_AND_CONSEQUENTIAL_USE.md) for the boundary and
the architecture gate that keeps this boundary from eroding.

## Not validated for regulated-sector compliance

PACIFY-X is not validated for HIPAA, GLBA, FCRA, ECOA, FERPA, COPPA, PCI-DSS, FedRAMP,
government contracting requirements, or any comparable sector regime. If you deploy it in a
regulated environment, establishing compliance is your responsibility and usually requires
controls beyond what a general-purpose developer tool provides.

## Deployment assumptions

- You run it on a machine you control.
- You choose and configure any external providers.
- You review AI output before acting on it.
- You decide what memory and knowledge to retain.
- You are the operator for your own regulatory context.

## Related documents

- [DISCLAIMER.md](DISCLAIMER.md) — limitations of the software and of certification.
- [AI_TRANSPARENCY.md](AI_TRANSPARENCY.md) — how AI involvement is disclosed.
- [AI_LIMITATIONS.md](AI_LIMITATIONS.md) — known failure modes.
- [MEMORY_PRIVACY_MODEL.md](MEMORY_PRIVACY_MODEL.md) — memory boundaries.