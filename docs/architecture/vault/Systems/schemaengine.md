---
canonical_id: "schemaengine"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Owned schema and reference closure

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Admits the supported JSON Schema subset, validates instances and computes a digest over referenced schema documents; corpus review checks ownership and smoke fixtures.

## Historical source state

Instance errors, contract closure digests and declared ownership counts.

## Limits and unknowns

Corpus fixture and owner-path checks do not prove every runtime producer/consumer calls validation or agrees on semantics.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1957]] — changed-file
- [[Evidence/S1955]] — changed-file
- [[Evidence/S1956]] — changed-file
- [[Evidence/S2272]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
