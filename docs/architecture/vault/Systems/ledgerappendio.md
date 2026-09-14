---
canonical_id: "ledgerappendio"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Authoritative ledger append and fsync

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Checks opened file identity then appends prepared bytes under the owner lock.

## Historical source state

Durable JSONL prefix before projection publication.

## Limits and unknowns

Failure after append is not rollback of committed events.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2525]] — changed-file
- [[Evidence/S2541]] — changed-file

## Directed relationships

- [[Systems/ledgercheckpointpublisher]] — publishes projections after event fsync (`E1239`)
