---
canonical_id: "serviceroute"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Service metadata ranking and refusal hints

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Ranks catalog entries by terms and fixed domain heuristics, exposes effects/approval hints and denial reasons.

## Historical source state

Selected candidates with authority_granted false.

## Limits and unknowns

Phrase detection is not authorization; no service connection. Golden evaluator does not check route valid or denials.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3024]] — changed-file

## Directed relationships

- [[Systems/servicehydrate]] — requires caller selection handoff (`E532`)
