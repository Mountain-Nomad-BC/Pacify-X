---
canonical_id: "ledgerhistorycompactor"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Ledger compact history and retained indexes

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Retains short detailed history plus permanent identity/evidence indexes and open admissions.

## Historical source state

Card history three; latest details one; work details eight.

## Limits and unknowns

Consumers must consult retained indexes or preserve invalidation state.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2495]] — changed-file

## Directed relationships

- [[Systems/ledgerworkguard]] — supplies compact lifecycle history (`E1243`)
- [[Systems/controlcardadvancement]] — limits retained historical bindings (`E1275`)
