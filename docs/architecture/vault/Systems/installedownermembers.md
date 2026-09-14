---
canonical_id: "installedownermembers"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Installed member ordering and receipt aggregation

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Starts Windows and Ubuntu smokes together, waits both, then executes exhaustive member.

## Historical source state

Three member results with receipt references.

## Limits and unknowns

Aggregate fields do not independently enumerate the control/profile denominator.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3953]] — same-file-bytes
- [[Evidence/S3959]] — same-file-bytes

## Directed relationships

- [[Systems/installedownerpublication]] — provides aggregate pass decision (`E1282`)
