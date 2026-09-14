---
canonical_id: "walklimits"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Bounded filesystem traversal

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Enumerates a deterministic tree with file, byte and depth ceilings and explicit reject, skip or contained-follow symbolic-link behavior.

## Historical source state

Sorted relative entries, counts or a structured failure.

## Limits and unknowns

The root is resolved first; exclusions prune before limits. Contained-follow mode rejects repeated directory identity. This is a traversal primitive, not a deletion authorization.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1647]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
