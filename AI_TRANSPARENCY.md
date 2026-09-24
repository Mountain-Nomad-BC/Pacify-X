# AI Transparency

PACIFY-X is an AI-assisted engineering environment. This document states plainly what that
means, in the terms the EU AI Act Article 50 transparency provisions care about and in plain
language for everyone else.

**No compliance certification is claimed.** This document records behaviour; it does not assert
that PACIFY-X is "AI Act compliant".

---

## 1. You are interacting with AI

When you use the PX Agent Console, the librarian, an agent worker, or any routed model, you are
interacting with an AI system. Responses are machine-generated.

PACIFY-X surfaces this in the interface: the Agent Console identifies the active model and route,
and status messages distinguish AI output from deterministic actions.

## 2. It may use third-party and local models

PACIFY-X uses whichever models you make available:

- **local models** running through the local runtime on your hardware;
- **external providers** you explicitly configure.

PACIFY-X ships no model of its own.

## 3. Model identity can change based on routing

Unless you pin a route, PACIFY-X may select a model based on capability, availability, privacy,
cost, and load. A reply may therefore come from a different model than a previous reply.

To keep identity stable: pin the route, or read the active-model indicator in the interface.
Every governed invocation returns a receipt recording the exact model and runtime used.

## 4. Model provider and runtime identity are inspectable

PACIFY-X records and can display:

- the model identity and, where available, its content hash;
- the runtime and its build identity;
- the provider;
- the route that was taken and why.

This is the mechanism behind "known AI behavior boundary": you can always find out *what*
produced an output.

## 5. Tool execution is separate from generation

A model **proposing** an action is not the same as an action **executing**.

- The model has no tool authority.
- Tool execution passes through PACIFY-X's ToolBroker and authority gates.
- Mutating or consequential actions require explicit approval where the contract demands it.
- A model cannot grant itself authority by asserting it.

If the interface says a tool ran, it ran through the governed path and produced a receipt. If it
only proposed, it did not run.

## 6. Generated content provenance

Where PACIFY-X can control content generation, it can preserve machine-readable provenance and
marking capability.

Where PACIFY-X merely **brokers** a third-party generator, marking obligations sit with that
generator. PACIFY-X will document which side owns what rather than implying it guarantees the
other's behaviour.

PACIFY-X does not claim unmarked output is human-created.

## 7. Human oversight

PACIFY-X is built around human oversight:

- risky actions are gated;
- destructive actions require approval;
- effects are receipted;
- outcomes are verified after a mutation;
- evidence is retained so a decision is reviewable afterwards.

The AI assists. You remain responsible for what is done in your environment.

## 8. What PACIFY-X does NOT claim

- It is not a substitute for a licensed professional (legal, medical, financial, or otherwise).
- It is not certified for consequential decision-making (see
  [HIGH_RISK_AND_CONSEQUENTIAL_USE.md](HIGH_RISK_AND_CONSEQUENTIAL_USE.md)).
- It does not guarantee that generated code is secure or correct.
- A passing certification is not a statement that the AI's *outputs* are correct.

## 9. Where to read more

- [INTENDED_USE.md](INTENDED_USE.md) — what PACIFY-X is for.
- [AI_LIMITATIONS.md](AI_LIMITATIONS.md) — how it fails.
- [HIGH_RISK_AND_CONSEQUENTIAL_USE.md](HIGH_RISK_AND_CONSEQUENTIAL_USE.md) — what it must not
  be used for.
- [docs/compliance/EU_AI_ACT.md](docs/compliance/EU_AI_ACT.md) — the detailed applicability
  analysis.