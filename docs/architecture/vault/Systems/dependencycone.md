---
canonical_id: "dependencycone"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Universal dependency declarations and revision cone

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Builds dependency-to-consumer graph and BFS-propagates supplied revision drift.

## Historical source state

Sorted stale cone with depths and gate labels.

## Limits and unknowns

No automatic writes/rebuild; cone trusts graph and only supplied current revisions.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2040]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
