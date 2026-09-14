---
canonical_id: "studiolateworker"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Installed Studio late-card fixture worker

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Exercises physical allocation, fork identity, preserved provenance and projection rollback with an independent framed hash.

## Historical source state

Grouped booleans and completed flag on stdout.

## Limits and unknowns

Caller owns disposable root; worker can overwrite scaffold; completed=false still exits zero unless consumer rejects.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1420]] — same-file-bytes

## Directed relationships

- [[Systems/versionallocation]] — tests physical occupancy and stale allocation (`E1482`)
- [[Systems/skillprojectionafter]] — compares preservation and rollback projections (`E1483`)
