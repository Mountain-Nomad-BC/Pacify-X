---
canonical_id: "profilebyteprojection"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Profile byte projection

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Copies top-level authoritative TOML profiles and detects extra projected names in check mode.

## Historical source state

Hash records and pre-write stale/extra lists.

## Limits and unknowns

Apply returns true even with retained extra files; absent source directory can mean empty success.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3546]] — same-file-bytes

## Directed relationships

- [[Systems/generatedcomparison]] — checks projected bytes and extra names (`E1200`)
