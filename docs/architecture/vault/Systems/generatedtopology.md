---
canonical_id: "generatedtopology"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Generated authority cycle analysis

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Builds declared input-to-generated-artifact edges and uses strongly connected components plus self-loop checks to reject authority cycles.

## Historical source state

Declared generation graph, SCCs, cycle failures and intentionally excluded live projections.

## Limits and unknowns

Acyclic generated authority differs from desirable runtime feedback. Coverage depends on declarations; excluded live receipt/head projections retain separate owners.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2209]] — changed-file
- [[Evidence/S1610]] — changed-file
- [[Evidence/S2207]] — same-file-bytes

## Directed relationships

- [[Systems/graphs]] — constrains generated authority dependencies (`E240`)
- [[Systems/generatedadapter]] — requires edge-key translation before adaptation (`E255`)
- [[Systems/reachabilitydeclarations]] — uses static artifact inventory (`E776`)
