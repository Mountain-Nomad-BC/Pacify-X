---
canonical_id: "facttime"
kind: system
layer: memory
currentness: changed-file
runtime_observed: false
certified: false
---
# Bitemporal fact selection

[[Layers/memory]] · [[Views/Full_Architecture]]

## Purpose

Separately filters when a fact was valid in the world and when it was known to the system, within one project and excluding revoked records.

## Historical source state

Selected input facts and a separately computed transitive invalidation set.

## Limits and unknowns

No database, fact capture, correction writer, or persistent invalidation driver is implemented by these functions.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1936]] — changed-file
- [[Evidence/S1934]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
