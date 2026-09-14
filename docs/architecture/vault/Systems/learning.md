---
canonical_id: "learning"
kind: system
layer: reasoning
currentness: changed-file
runtime_observed: false
certified: false
---
# Experience and learning state machine

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Captures evidence-bound operations, extracts supplied patterns and forms immutable challenger hypotheses under explicit transitions.

## Historical source state

Signed learning pipeline events/head, operation hashes, frozen revision and dependency hashes.

## Limits and unknowns

Transitions require explicit host approval; observations and metrics are submitted by callers.

## Historical suggested evolution

Learning changes candidate state and may feed the separately governed canonical knowledge path.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2293]] — changed-file
- [[Evidence/S2289]] — changed-file
- [[Evidence/S2291]] — changed-file

## Directed relationships

- [[Systems/comparison]] — freezes hypotheses and records trials (`E076`)
