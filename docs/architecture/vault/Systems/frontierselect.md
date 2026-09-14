---
canonical_id: "frontierselect"
kind: system
layer: reasoning
currentness: changed-file
runtime_observed: false
certified: false
---
# Decision blocker frontier and priority proposal

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Checks ticket/blocker graph, rejects cycles and returns unclaimed unresolved tickets with all blockers closed.

## Historical source state

Ordered ticket rows and frontier-only content hash.

## Limits and unknowns

Does not acquire claims or verify closure evidence. blocked/in_progress labels alone do not exclude readiness.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2672]] — changed-file
- [[Evidence/S2673]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
