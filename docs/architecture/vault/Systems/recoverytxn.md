---
canonical_id: "recoverytxn"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Recovery replacement and preservation transaction

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Prepares verified replacement, preserves previous destination, replaces and then publishes quarantine/evidence.

## Historical source state

Recovered/escalated result, previous artifact and transaction journals.

## Limits and unknowns

Rollback covers replacement block, not later preservation publication and final evidence.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2640]] — same-file-bytes

## Directed relationships

- [[Systems/streamcheckpoint]] — returns recovery decision before terminal checkpoint (`E575`)
