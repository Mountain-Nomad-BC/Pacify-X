---
canonical_id: "testreceiptstatus"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Section group and chunk receipt consumers

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Reads freshness and passing status for execution/release decisions.

## Historical source state

Currentness and required-denominator flags.

## Limits and unknowns

Section/group skip receipt hash; group_status omits index_current; chunk consumer is stricter.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3217]] — changed-file
- [[Evidence/S3206]] — changed-file
- [[Evidence/S3209]] — changed-file

## Directed relationships

- [[Systems/testfullowner]] — admits current sections and group reuse (`E859`)
- [[Systems/preflightstatic]] — supplies group readiness flags (`E861`)
- [[Systems/completionprojection]] — projects section and group status (`E862`)
