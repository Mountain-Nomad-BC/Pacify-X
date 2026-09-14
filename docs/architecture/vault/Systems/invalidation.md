---
canonical_id: "invalidation"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Dependency invalidation and projection freshness

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Computes affected dependency cones and identifies stale generated projections against declared source revisions.

## Historical source state

Dependency authority, current revision map, stale nodes and rebuild plan.

## Limits and unknowns

Propagation is only as complete as the declared dependency graph and current revision inputs.

## Historical suggested evolution

Source or trust changes can prevent stale projections from being reused and require rebuilding.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2043]] — changed-file
- [[Evidence/S2700]] — changed-file

## Directed relationships

- [[Systems/learninggate]] — blocks promotion on dependency drift (`E083`)
- [[Systems/graphs]] — requires stale projection rebuild (`E099`)
- [[Systems/projectmap]] — invalidates affected source context (`E100`)
