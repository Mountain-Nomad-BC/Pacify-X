---
canonical_id: "cachemovepublication"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Python cache move and post-effect receipt

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Moves selected caches into a timestamped recovery directory and reconciles recorded file hashes afterward.

## Historical source state

Recoverable paths and receipt only after all moves and reconciliation.

## Limits and unknowns

No immediate equality gate, pre-move durable journal or rollback; nested cache destinations can change shutil.move placement.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3662]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
