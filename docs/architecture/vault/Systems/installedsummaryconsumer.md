---
canonical_id: "installedsummaryconsumer"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Installed operational evidence consumer

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Cross-binds artifact, claims, exact three members and selected nested report/count fields.

## Historical source state

Validated installed summary for downstream stages.

## Limits and unknowns

Smoke/lifecycle bodies only hash-checked; no signed certificate or full source freshness proof.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3993]] — changed-file
- [[Evidence/S3987]] — changed-file

## Directed relationships

- [[Systems/releasepackageaudit]] — checks package receipt fields and hash (`E921`)
- [[Systems/releaseinstallaudit]] — checks installation receipt denominator (`E922`)
