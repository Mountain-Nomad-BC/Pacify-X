---
canonical_id: "resources"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Resource lifecycle and safe reclamation

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Registers owned paths/processes, reconciles lifecycle and reclaims eligible ephemerals under retention, ownership and boundary gates.

## Historical source state

Resource ledger, retention classification, process/path ownership and cleanup receipts.

## Limits and unknowns

User-owned, external, authoritative or unknown material cannot be treated as disposable.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2983]] — changed-file
- [[Evidence/S2985]] — changed-file

## Directed relationships

- [[Systems/supervisor]] — constrains closure and cleanup (`E102`)
- [[Systems/certificate]] — requires reconciled owned lifecycle (`E111`)
