---
canonical_id: "cognav"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Unified cognitive navigation

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Indexes cognitive asset metadata and returns bounded hierarchical search results and hydration plans.

## Historical source state

Cognitive map and selected hydration plan.

## Limits and unknowns

This is a discovery index, distinct from canonical knowledge and project source graphs.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1909]] — same-file-bytes
- [[Evidence/S1898]] — changed-file

## Directed relationships

- [[Systems/cognitive]] — plans selected reasoning hydration (`E123`)
- [[Systems/graphread]] — supplies the cognitive graph projection (`E260`)
