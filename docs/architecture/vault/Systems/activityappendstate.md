---
canonical_id: "activityappendstate"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Local activity append then state publication

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Appends hash-linked JSONL before replacing current state.

## Historical source state

Serialized writers with separate log/state commits.

## Limits and unknowns

Prior log parse is checked, but hash integrity is not enforced before append.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S865]] — same-file-bytes

## Directed relationships

- [[Systems/extensioneventpublisher]] — queues canonical event after successful local append (`E1063`)
- [[Systems/activityreadintegrity]] — supplies separate log and state observations (`E1064`)
