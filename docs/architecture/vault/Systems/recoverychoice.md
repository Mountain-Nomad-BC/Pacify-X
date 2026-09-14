---
canonical_id: "recoverychoice"
kind: system
layer: reasoning
currentness: changed-file
runtime_observed: false
certified: false
---
# Recovery policy proposal ordering

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Chooses stop, escalate, rollback, fallback or bounded retry from supplied facts.

## Historical source state

Non-authorizing RecoveryDecision.

## Limits and unknowns

No authored runtime caller found; eligible fallback precedes idempotence/retry budget.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2785]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
