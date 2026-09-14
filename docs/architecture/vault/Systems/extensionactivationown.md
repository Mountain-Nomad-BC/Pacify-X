---
canonical_id: "extensionactivationown"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# Extension subscription rollback transaction

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Registers disposables immediately, commits ownership or reverse-disposes pending resources on activation throw.

## Historical source state

Synchronous ownership transaction.

## Limits and unknowns

Does not await async disposals or recover effects before registration.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S860]] — same-file-bytes
- [[Evidence/S1065]] — changed-file

## Directed relationships

- [[Systems/extensioneventpublisher]] — owns publisher disposal (`E981`)
