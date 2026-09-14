---
canonical_id: "pythonsurfacewriter"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Python ownership projection publication

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Runs helper harness and surface classifier then writes map with map_current true.

## Historical source state

Ownership map and combined validity exit.

## Limits and unknowns

Projection writes before final invalid exit; current map is distinct from passing evidence.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3553]] — same-file-bytes

## Directed relationships

- [[Systems/exacttoolaggregate]] — runs harness before map generation (`E1132`)
