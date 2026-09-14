---
canonical_id: "versionallocation"
kind: system
layer: governance
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Physical version allocation and revalidation

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Computes first available stable patch from source revision and physical occupancy, then revalidates source/tree/occupancy bindings before owner publication.

## Historical source state

Allocation observation with source revision/content/occupancy hashes and timestamp.

## Limits and unknowns

No reservation or lock in allocation itself; timestamp checks syntax rather than age. External-authenticated skill hashes are caller supplied here. Mutable top-level runs excluded from source tree.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3138]] — same-file-bytes
- [[Evidence/S3139]] — same-file-bytes

## Directed relationships

- [[Systems/studiophys]] — reads bounded predecessor and occupancy (`E461`)
