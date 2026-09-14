---
canonical_id: "specialists"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Specialist agent routing

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Chooses a primary specialist and bounded reviewers from metadata, then compiles a Studio-bound request.

## Historical source state

Route receipt, specialist revision, reviewers and queued Studio checkpoint.

## Limits and unknowns

Routing grants no authority and hydrates zero bodies; adapter submission queues a run but does not itself execute the specialist.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1557]] — changed-file
- [[Evidence/S1513]] — same-file-bytes

## Directed relationships

- [[Systems/agent]] — queues Studio-owned specialist request (`E117`)
