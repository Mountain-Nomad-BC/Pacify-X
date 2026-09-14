---
canonical_id: "activityattestation"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Local metadata versus canonical activity attestation

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Maps event vocabulary and strips actual scope paths/content for canonical SDK event.

## Historical source state

Non-enumerable canonical event passed separately to publisher.

## Limits and unknowns

Canonical event is formed before local task/claim enrichment; scope/effect details differ.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S881]] — same-file-bytes
- [[Evidence/S1097]] — changed-file

## Directed relationships

- [[Systems/activityappendstate]] — records local event with attestation metadata (`E1062`)
