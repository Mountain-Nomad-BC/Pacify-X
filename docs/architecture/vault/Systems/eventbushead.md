---
canonical_id: "eventbushead"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Anchored current-head read

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Locks publication, recovers WAL and checks current envelope/state/head/anchor plus immediate previous link.

## Historical source state

Current event/revision and explicit verification scope.

## Limits and unknowns

Not full ancestry verification; reads can recover and write.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2476]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
