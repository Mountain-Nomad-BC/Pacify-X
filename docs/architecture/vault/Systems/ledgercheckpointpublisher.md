---
canonical_id: "ledgercheckpointpublisher"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Ledger snapshot delta and head publication

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Publishes derived snapshot or content-addressed cumulative delta, then compact head.

## Historical source state

Hash-linked snapshot/head/delta artifacts.

## Limits and unknowns

Separate atomic file replacements are not one atomic multi-file transaction.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2498]] — changed-file
- [[Evidence/S2544]] — changed-file

## Directed relationships

- [[Systems/ledgercheckpointreader]] — provides exact head snapshot and delta bindings (`E1240`)
