---
canonical_id: "envstore"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Environment shard publication

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Writes content-addressed detail/data shards, replaces compact current index, then appends an environment event.

## Historical source state

Per-shard hashes, content hash, current snapshot hash, TTL, generation and added/removed IDs.

## Limits and unknowns

Multiple commit points; existing shard files are reused without producer verification. Shard producer has no matching8MiB size cap. A memory-only refresh skips this stage.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S973]] — same-file-bytes

## Directed relationships

- [[Systems/envread]] — supplies current index and hash-bound shards (`E373`)
