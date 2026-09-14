---
canonical_id: "projectionfreshness"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Projection hashing invalidation and rebuild categories

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Checks declared revisions and transitive consumers, groups synchronous versus blocking rebuilds.

## Historical source state

Stale outputs and rebuild plan.

## Limits and unknowns

Categories are not topologically ordered execution; stored staleness projection can label all current without reads.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2701]] — changed-file
- [[Evidence/S2702]] — changed-file

## Directed relationships

- [[Systems/affectedproofmeta]] — may supply stale projection requirements (`E650`)
