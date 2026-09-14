---
canonical_id: "studiohostreceipt"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Host create receipt classification

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Distinguishes exact created/recovered schemas from unverified commit outcome and binds skill source token/tree/inventory.

## Historical source state

Created, recovered or commit-outcome-unverified decision.

## Limits and unknowns

Agent/workflow hash fields checked structurally rather than independently reading every backend artifact.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1285]] — same-file-bytes
- [[Evidence/S1306]] — same-file-bytes

## Directed relationships

- [[Systems/studiopostcommit]] — selects valid success or unverified notification path (`E1033`)
