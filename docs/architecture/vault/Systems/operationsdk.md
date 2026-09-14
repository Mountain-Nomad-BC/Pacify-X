---
canonical_id: "operationsdk"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Operation event construction and context SDK

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Deep-copies caller event payload, checks SDK/schema and emits lifecycle variants through a callback.

## Historical source state

Validated event dictionaries and started/completed/failed emissions.

## Limits and unknowns

Does not allocate new event identity or timestamps for lifecycle variants, authenticate actors or observe effects.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2248]] — same-file-bytes

## Directed relationships

- [[Systems/routedeclarations]] — validates event schema and capture label (`E750`)
