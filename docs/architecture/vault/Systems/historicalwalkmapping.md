---
canonical_id: "historicalwalkmapping"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Historical live-walk report mapping

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Maps fixed report IDs and feature families into stable card/report events.

## Historical source state

Discovered cards and report reconciliation proposals.

## Limits and unknowns

Feature-name reuse and legacy report format limit current applicability.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3869]] — same-file-bytes

## Directed relationships

- [[Systems/ledgerappendplanner]] — submits discovered cards and report mappings (`E1259`)
