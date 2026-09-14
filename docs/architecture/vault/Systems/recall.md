---
canonical_id: "recall"
kind: system
layer: memory
currentness: changed-file
runtime_observed: false
certified: false
---
# Memory ranking and bounded context

[[Layers/memory]] · [[Views/Full_Architecture]]

## Purpose

Filters project/ACL/lifecycle eligibility, fuses available retrieval signals and materializes plan-bound context under item/byte/token limits.

## Historical source state

Memory query plan, ranked records and immutable materialization receipt.

## Limits and unknowns

The richer ranker accepts semantic/graph scores from callers; it does not generate embeddings itself.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2371]] — changed-file
- [[Evidence/S2352]] — same-file-bytes

## Directed relationships

- [[Systems/agent]] — materializes bounded memory bindings (`E055`)
