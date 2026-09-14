---
canonical_id: "envread"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Environment stored readers and freshness

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Checks current schema/hash then lazily loads and hashes requested shards; returns subject slices, extension details or full graph.

## Historical source state

Available/unavailable response, observation hash/freshness and selected records.

## Limits and unknowns

Dataset8MiB limit applies before full read; pagination applies after parsing. Containment is lexical. Stale active-environment downgrade is specific to environment records; graph properties retain captured state.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S974]] — same-file-bytes
- [[Evidence/S844]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
