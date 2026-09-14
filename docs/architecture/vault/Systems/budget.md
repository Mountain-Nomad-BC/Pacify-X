---
canonical_id: "budget"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Provider budgets and invocation identity

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Reserves and reconciles bounded provider usage and detects duplicate invocations.

## Historical source state

Budget ledger, reservations, usage and invocation IDs.

## Limits and unknowns

Recorded usage constrains later invocations but does not train or alter the model.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2712]] — changed-file

## Directed relationships

- [[Systems/provider]] — reserves and reconciles invocation usage (`E040`)
- [[Systems/wal]] — commits budget state and receipt together (`E404`)
