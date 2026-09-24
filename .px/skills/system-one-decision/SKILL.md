---
name: system-one-decision
description: Use the governed System-1 decision engine for bounded, typed decisions expressed as a finite question over a small compiled state. Advisory only - it recommends, classifies, and scores, while Pacify-X decides what is permitted.
---
# System-1 Decision Layer (Laya)

Use the governed System-1 decision engine for **bounded, typed decisions** that this system
can express as a finite question over a small compiled state. This is advisory machinery: it
recommends, classifies, and scores. Pacify-X decides what is permitted.

## When to use this skill

Use it when all of the following hold:

- the decision reduces to a finite set of options, an ordered rubric, or a yes/no proposition;
- the relevant facts fit a small compiled state, not a transcript or a file dump;
- deterministic parsing has already failed to resolve the question outright;
- the cost of a generative model call would be disproportionate to the decision.

Do **not** use it for: free-form generation, explanation, debugging, multi-file causal
analysis, code synthesis, open-ended planning, or anything requiring memory of a conversation.
Those belong to the resident librarian and the on-demand usage worker.

## Decision forms

| Form | Meaning | Example question |
|---|---|---|
| `choice` | select among bounded labelled options | which model tier should handle this task? |
| `score` | place the state on an ordered rubric | how urgent is this request? |
| `noul` | calibrated probability that a proposition is true | is the current model likely to succeed? |

## Mandatory procedure

1. **Resolve deterministically first.** Parse explicit commands, paths, identifiers, action
   names, and known capability ids. Only unresolved semantic ambiguity reaches this layer.
2. **Compile the state.** Reduce PX facts to a bounded envelope through the Decision State
   Compiler. Missing facts must be recorded as explicitly unknown (`<field>_known: false`).
   Never fill a missing value with a plausible number.
3. **Ask the decision gateway.** Call the single gateway entry point with the decision id, the
   compiled facts, and the typed questions. Do not call the decision engine directly.
4. **Apply the versioned threshold policy.** The raw distribution and the acceptance decision
   stay separate. Acceptance is a policy outcome, not the model's opinion.
5. **Respect ambiguity.** If the top probability or the margin misses the threshold, take the
   policy's ambiguity action (`escalate`, `clarify`, `queue_review`, `no_op`, `reject`) instead
   of acting on a weak distribution.
6. **Fall back deterministically.** If the engine is unavailable or answers outside contract,
   use the deterministic path. Never substitute a guessed answer.

## Hard boundaries

- Confidence is not authority. A 0.99 probability grants no permission, proves no fact, and
  authorises no mutation. Deterministic preconditions, permissions, source requirements, and
  contracts are checked separately and always.
- This layer never fabricates a canonical identifier. It may narrow a mention to a candidate
  class; the registries resolve the actual entity.
- Destructive, release, security, admission, and installation decisions are advisory-only and
  must never be accepted from a score.
- Every decision is recorded with its model checkpoint identity, input state hash, latency,
  and policy evaluation so the outcome is auditable.

## Failure behaviour

| Condition | Required behaviour |
|---|---|
| engine unavailable | deterministic fallback, recorded as such |
| engine returns an out-of-contract shape | typed protocol failure, no answer used |
| state exceeds the token budget | drop optional fields, keep required, record unknown |
| threshold not met | apply the policy's ambiguity action |

## Validation

Verified by `tests/test_system_one_decision.py`: policy registry shape, explicit-unknown
compilation, threshold and margin gating, ambiguity routing, unavailable-engine fallback,
and typed protocol failure.