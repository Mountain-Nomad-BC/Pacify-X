---
canonical_id: "quarantinetxn"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Quarantine inventory move and compensation

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Inventories candidate files, journals intent, verifies known hashes, moves and records completion.

## Historical source state

Moved inventory, rollback journal or committed event.

## Limits and unknowns

No exact two-tree snapshot; final event/commit outside compensating block.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2639]] — same-file-bytes

## Directed relationships

- [[Systems/streamcheckpoint]] — returns moved inventory before terminal checkpoint (`E576`)
