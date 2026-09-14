---
canonical_id: "nativestatesync"
kind: system
layer: governance
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Declared specialty and commissioned projection sync

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Copies specialty state labels and regenerates commissioned skill rows.

## Historical source state

Updated package/ledger/catalog/hash projections.

## Limits and unknowns

Metadata reconciliation does not execute lifecycle admission; multi-file direct writes can partially apply.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3910]] — same-file-bytes
- [[Evidence/S3861]] — same-file-bytes

## Directed relationships

- [[Systems/skillstatus]] — copies declared state into projections (`E891`)
