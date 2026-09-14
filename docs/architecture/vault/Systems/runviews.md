---
canonical_id: "runviews"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Run snapshots and cancellation signal

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Provides locked history reads, unlocked bounded snapshot lists, cheap signed-head polling and stale heartbeat reconciliation.

## Historical source state

Displayed run page, requested_state and occasional heartbeat write.

## Limits and unknowns

List caps lexical IDs before time ordering and can race event/head publication. Signal triggers only pause/cancel requests; stale reconciliation checks heartbeat before a separately locked transition.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3147]] — same-file-bytes
- [[Evidence/S3149]] — same-file-bytes

## Directed relationships

- [[Systems/supervisor]] — signals cooperative pause or cancel (`E442`)
- [[Systems/supervisebudget]] — supplies cancellation callback with heartbeat effects (`E453`)
