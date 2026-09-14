---
canonical_id: "candidatedriver"
kind: system
layer: release
currentness: changed-file
runtime_observed: false
certified: false
---
# Twelve-stage release candidate driver

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Selects next pending owner and enforces no replay of running/failed attempts.

## Historical source state

Whole-file automation journal and step result.

## Limits and unknowns

Journal not config-hashed or locally locked; changed configuration can affect resume.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3989]] — changed-file
- [[Evidence/S3991]] — changed-file

## Directed relationships

- [[Systems/candidateprocess]] — dispatches configured command tuple (`E918`)
- [[Systems/hygienereadiness]] — requires fresh initial readiness (`E928`)
- [[Systems/controlcompletenesscheck]] — checks final operational reconciliation status (`E1283`)
- [[Systems/cohesiondenominator]] — runs exact cohesion check and apply commands (`E1287`)
