---
canonical_id: "foundrymaterialize"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Foundry multi-file candidate materialization

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Creates a new bundle directory, writes generated files and finally a receipt.

## Historical source state

Candidate source files and hashes.

## Limits and unknowns

No transaction/recovery/custody registration; partial directory blocks retry; duplicate calculation IDs overwrite file-map entries.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2312]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
