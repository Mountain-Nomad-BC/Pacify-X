---
canonical_id: "nativebackupcustody"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Skill inventory backup and exact-byte restore

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Inventories/copies/verifies listed backups and reconstructs retained line endings/order.

## Historical source state

Custody metadata and optional restored tree.

## Limits and unknowns

Unbounded inventory, manifest path trust, empty-source and empty-destination asymmetries.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2442]] — changed-file
- [[Evidence/S2448]] — changed-file
- [[Evidence/S2445]] — changed-file

## Directed relationships

- [[Systems/nativecomparetrees]] — provides shared inventory and tree hash (`E884`)
