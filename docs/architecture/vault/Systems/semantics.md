---
canonical_id: "semantics"
kind: system
layer: memory
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Structured semantic memory

[[Layers/memory]] · [[Views/Full_Architecture]]

## Purpose

Attaches bounded structured payloads, typed entities/relations, namespace and deterministic exact routing keys to records.

## Historical source state

SemanticEnvelope, semantic identity hash, entities and typed relations.

## Limits and unknowns

Required/excluded context are serialized declarations, not evaluated by semantic query signals or reviewed recall/materialization paths. Payload bounds are validation limits after input construction; no owned embedding service is established.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3014]] — same-file-bytes
- [[Evidence/S3016]] — same-file-bytes

## Directed relationships

- [[Systems/vault]] — supplies typed record semantics (`E051`)
- [[Systems/memoryindex]] — projects routing and graph fields (`E053`)
- [[Systems/vault]] — supplies exact key and structured search signals (`E425`)
