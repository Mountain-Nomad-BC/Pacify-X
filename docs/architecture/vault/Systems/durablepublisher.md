---
canonical_id: "durablepublisher"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Authenticated run event and head publication

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Serializes legal state transitions and heartbeats, signs events before head replacement and repairs exactly one authenticated trailing event.

## Historical source state

Event ancestry, current head and separate recovery receipt.

## Limits and unknowns

Approved is a caller boolean at this primitive. Event/head are separate writes; normal reads fail closed in the crash window until explicit recovery. Head repair precedes recovery receipt.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3154]] — same-file-bytes

## Directed relationships

- [[Systems/runviews]] — supplies history and head to read surfaces (`E441`)
- [[Systems/filelease]] — serializes run event and head access (`E458`)
