---
canonical_id: "studioverifierlocator"
kind: system
layer: governance
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Verifier description and authority initialization

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Returns host approval verifier path by constructing authority store.

## Historical source state

Descriptor plus possible initialized or migrated authority state.

## Limits and unknowns

Read-only description does not imply absence of constructor writes.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3109]] — same-file-bytes
- [[Evidence/S3118]] — same-file-bytes

## Directed relationships

- [[Systems/studioauthority]] — constructs canonical authority store (`E868`)
