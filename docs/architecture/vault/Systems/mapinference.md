---
canonical_id: "mapinference"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Project dependency call and traceability inference

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Joins imports and name-based calls, static test associations, declarations and ownership rules into typed projections.

## Historical source state

Graphs and hypothesis-based test/runtime/data/ownership relationships.

## Limits and unknowns

Call resolved flag is lexical, service names can collide, and type/route/runtime labels are not observations of deployed execution.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2650]] — same-file-bytes
- [[Evidence/S2649]] — same-file-bytes
- [[Evidence/S2660]] — same-file-bytes
- [[Evidence/S2647]] — same-file-bytes

## Directed relationships

- [[Systems/mapindexbuild]] — projects selected entity metadata (`E548`)
