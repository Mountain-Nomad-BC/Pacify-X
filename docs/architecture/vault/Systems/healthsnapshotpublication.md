---
canonical_id: "healthsnapshotpublication"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Health snapshot and optional output publication

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Writes snapshot then optional health claims and reconciled coverage.

## Historical source state

Up to three output files and CLI validity.

## Limits and unknowns

No output alias guard, pair/group rollback or final readback; initial valid means snapshot generation.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3534]] — same-file-bytes

## Directed relationships

- [[Systems/installedhealthprojection]] — optionally rereads installed receipt for canonical claims (`E1218`)
- [[Systems/livecoverageproof]] — optionally reconciles active route evidence and freshness (`E1219`)
