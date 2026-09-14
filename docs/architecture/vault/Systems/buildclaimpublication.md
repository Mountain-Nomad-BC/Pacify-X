---
canonical_id: "buildclaimpublication"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Build-claim and README publication

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Computes counts then fsyncs/replaces claims and updates README.

## Historical source state

Two projected artifacts.

## Limits and unknowns

Claims replace precedes README failure; no shared transaction or rollback.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3441]] — same-file-bytes
- [[Evidence/S1654]] — same-file-bytes

## Directed relationships

- [[Systems/buildcountfacts]] — computes before write and validates afterward (`E815`)
