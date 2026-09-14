---
canonical_id: "memoryclusters"
kind: system
layer: memory
currentness: changed-file
runtime_observed: false
certified: false
---
# Memory graph BFS clusters

[[Layers/memory]] · [[Views/Full_Architecture]]

## Purpose

Builds undirected adjacency and capped BFS groups with union provenance and first32 terms.

## Historical source state

Cluster membership, missing endpoints and truncation flag.

## Limits and unknowns

Materializes full node iterable first; duplicate IDs overwrite, edges are unbounded and terms are lexical.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2379]] — changed-file

## Directed relationships

- [[Systems/memrepair]] — offers cluster graph for separate health planning (`E672`)
