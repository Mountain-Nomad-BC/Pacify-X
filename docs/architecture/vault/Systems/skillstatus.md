---
canonical_id: "skillstatus"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Native package lifecycle and eligibility

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Separates active procedural packages from mapped-deferred external wrappers and checks package selection before hydration.

## Historical source state

Catalog/index lifecycle, domain grants, body pointer and body hash.

## Limits and unknowns

A suggestive learning name and current validation_freshness do not make a mapped_deferred package active.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2437]] — changed-file
- [[Evidence/S2441]] — changed-file
- [[Evidence/S1499]] — same-file-bytes
- [[Evidence/S1497]] — same-file-bytes
- [[Evidence/S1496]] — same-file-bytes

## Directed relationships

- [[Systems/procedures]] — releases one eligible body to its caller (`E207`)
