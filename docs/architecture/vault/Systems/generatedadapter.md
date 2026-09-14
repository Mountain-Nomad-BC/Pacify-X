---
canonical_id: "generatedadapter"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Generated graph invalidation adapter

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Converts edges carrying from/to keys into dependency/consumer records and creates revision-bound nodes from the accepted edges.

## Historical source state

Adapted dependency nodes and edges.

## Limits and unknowns

This adapter reads from/to only. runtime.generated_dependency_graph emits source/target, so direct composition would drop those edges. The inspected test supplies from/to and does not test that producer pairing.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2041]] — changed-file
- [[Evidence/S4189]] — same-file-bytes

## Directed relationships

- [[Systems/invalidation]] — provides normalized graph input records (`E256`)
