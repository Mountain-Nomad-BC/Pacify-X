---
canonical_id: "intakeclosureledger"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Intake open snapshot and close ledger

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Appends exclusive event files and requires two matching snapshots plus current equality before close.

## Historical source state

Open/closed status and accepted snapshot.

## Limits and unknowns

Snapshots are selected across whole history rather than current reopen epoch; no shared sequence lock.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2254]] — same-file-bytes
- [[Evidence/S2253]] — same-file-bytes

## Directed relationships

- [[Systems/intakefilesnapshot]] — compares last two snapshots with current files (`E769`)
