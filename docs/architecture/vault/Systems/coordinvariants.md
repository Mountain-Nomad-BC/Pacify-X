---
canonical_id: "coordinvariants"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# JavaScript coordination invariants

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Checks state shape, unique identities, DAG/plan ownership, finite budgets, active claim expiry/fences and exact event/revision/counter transition links.

## Historical source state

Conformance violation IDs or typed invariant rejection.

## Limits and unknowns

requireSeal false only skips seal checking; it still checks active-claim expiry. This runs before withState expiry normalization, so expired stored claims block the normal mutation path.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1257]] — changed-file
- [[Evidence/S944]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
