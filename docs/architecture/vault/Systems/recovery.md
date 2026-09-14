---
canonical_id: "recovery"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Durable checkpoint recovery

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Validates persisted state, reconciles resume and selects bounded recovery instead of blind retries.

## Historical source state

Checkpoint identity, failure fingerprint, durable state and retry decision.

## Limits and unknowns

Different stores have owner-specific recovery procedures; one success does not certify every state plane.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2789]] — changed-file
- [[Evidence/S2785]] — changed-file
- [[Evidence/S2334]] — same-file-bytes

## Directed relationships

- [[Systems/recoverychoice]] — offers recovery decision primitive (`E618`)
