---
canonical_id: "durablemigration"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Version migration through WAL

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Preserves exact old bytes and commits migrated state with receipt.

## Historical source state

Backup, new state and migration receipt.

## Limits and unknowns

WAL recovery precedes some request rejection; no owner lock/source compare-and-swap.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2787]] — changed-file

## Directed relationships

- [[Systems/walcommit]] — commits backup state and receipt (`E616`)
