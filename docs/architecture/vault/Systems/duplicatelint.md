---
canonical_id: "duplicatelint"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Exact-name primitive duplicate lint

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Scans Python function names and selected dynamic lookups after exception validation.

## Historical source state

Duplicate/ambiguity findings and informational aliases.

## Limits and unknowns

Limited syntax/scope; leaf-name collisions and duplicate classes are not fully covered.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2612]] — same-file-bytes

## Directed relationships

- [[Systems/primitivedecl]] — validates registry before candidate scan (`E629`)
