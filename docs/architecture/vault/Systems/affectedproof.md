---
canonical_id: "affectedproof"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Dependency-scoped proof planning

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Expands changed cards through dependency invalidation, resolves affected tests to sole groups and builds focused/negative/downstream proof requirements.

## Historical source state

Changed-card cone, tests, sections, stale projections and proof completion requirements.

## Limits and unknowns

Planning checks supplied completion sets; it does not run tests. Broad profiles remain excluded during repair.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1508]] — same-file-bytes
- [[Evidence/S1509]] — same-file-bytes
- [[Evidence/S1698]] — changed-file

## Directed relationships

- [[Systems/invalidation]] — computes changed-card dependency cone (`E190`)
- [[Systems/tests]] — specifies focused and affected test obligations (`E193`)
