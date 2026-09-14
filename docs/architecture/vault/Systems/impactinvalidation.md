---
canonical_id: "impactinvalidation"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Impact to invalidation star projection

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Converts valid-tagged impact target, affected files and tests into caller-revision nodes and target-to-consumer edges.

## Historical source state

Typed nodes and dependency/consumer pairs.

## Limits and unknowns

No hash/currentness/complete-coverage check; missing revisions become empty and original paths/direction are not preserved.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2644]] — changed-file

## Directed relationships

- [[Systems/invalidation]] — supplies typed revision graph inputs (`E538`)
