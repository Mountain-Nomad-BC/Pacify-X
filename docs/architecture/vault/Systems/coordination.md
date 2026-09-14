---
canonical_id: "coordination"
kind: system
layer: scope
currentness: changed-file
runtime_observed: false
certified: false
---
# Coordination and repository claims

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Tracks actors, task DAGs, claims, checkpoints and non-canonical coordination memory under state invariants.

## Historical source state

Coordination state and chained events; active claim scopes.

## Limits and unknowns

Coordination memory is an intake/reference surface, not canonical project memory.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S943]] — changed-file
- [[Evidence/S3065]] — changed-file
- [[Evidence/S942]] — changed-file

## Directed relationships

- [[Systems/effects]] — provides active repository claim (`E016`)
- [[Systems/wal]] — checks state-transition invariants (`E017`)
- [[Systems/sidebarstate]] — supplies task state for weighted progress (`E288`)
