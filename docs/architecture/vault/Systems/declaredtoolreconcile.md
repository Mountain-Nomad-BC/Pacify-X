---
canonical_id: "declaredtoolreconcile"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Tool target reference and lazy-index hash chain

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Builds consistent target-source hashes, reference hashes and owner lazy index outputs.

## Historical source state

Ordered expected output mapping.

## Limits and unknowns

Current-byte consistency differs from admissibility, provenance or behavioral verification.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3865]] — same-file-bytes

## Directed relationships

- [[Systems/generatedcomparison]] — compares hash-chain rendered outputs (`E1202`)
