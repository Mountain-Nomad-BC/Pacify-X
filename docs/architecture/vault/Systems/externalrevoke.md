---
canonical_id: "externalrevoke"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# External candidate revocation marker

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Writes a revocation marker while preserving source candidate receipt.

## Historical source state

Revocation JSON.

## Limits and unknowns

Plan ID is interpolated into path without portable grammar or containment enforcement.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2160]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
