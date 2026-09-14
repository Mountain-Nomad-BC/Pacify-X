---
canonical_id: "activityledger"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Host activity ledger and recovery

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Serializes activity metadata, appends chained events before publishing state, derives active/stale views, and repairs hash ancestry with retained backups.

## Historical source state

Activity JSONL, state head, stale cancellation events and pre-repair copies.

## Limits and unknowns

Cancellation is a ledger transition, not proof of process termination. Repair reseals existing records; valid repaired ancestry does not authenticate their original truth.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S866]] — same-file-bytes
- [[Evidence/S877]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
