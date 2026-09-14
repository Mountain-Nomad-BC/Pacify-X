---
canonical_id: "capacityleases"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Logical model capacity reservation ledger

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Serializes capacity reserve/release for matching hardware fingerprint and selected device.

## Historical source state

Reservation and release receipts with active ledger state.

## Limits and unknowns

Unreadable/malformed state resets empty. No expiry/PID/restart recovery, no idempotent run reservation and no device-index partition. Capacity comes from caller-hashed placement.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2138]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
