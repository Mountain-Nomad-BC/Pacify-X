---
canonical_id: "schemainstance"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Owned schema admission and instance evaluation

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Admits supported keywords and local references, then recursively checks caller instance against schema rules.

## Historical source state

Success or structured constraint error.

## Limits and unknowns

Limited keyword/format surface, Python-specific comparison behavior and no global schema/instance/regex workload bound.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1949]] — changed-file
- [[Evidence/S1957]] — changed-file
- [[Evidence/S1950]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
