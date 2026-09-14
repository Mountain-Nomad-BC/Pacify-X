---
canonical_id: "ledgerstatereducer"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Ledger replay and state reduction

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Reduces ordered hash-chain events into card, control, report and work state.

## Historical source state

Append-only history authority and derived state.

## Limits and unknowns

Replay admits some legacy states deliberately; consistency is not authenticity.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2557]] — changed-file

## Directed relationships

- [[Systems/ledgerhistorycompactor]] — compacts detailed history after reduction (`E1242`)
- [[Systems/ledgerdashboardcounts]] — derives separate ownership and observation denominators (`E1244`)
