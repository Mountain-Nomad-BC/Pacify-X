---
canonical_id: "releaseautomation"
kind: system
layer: release
currentness: changed-file
runtime_observed: false
certified: false
---
# Release candidate journal and owner driver

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Selects exactly the next eligible configured owner, rechecks prior passed postconditions and retains admission, execution and closure records.

## Historical source state

Candidate-bound automation journal and aggregate campaign report.

## Limits and unknowns

Owner failure blocks retries for that candidate. The aggregate report counts stages performed in the current invocation; a resumed invocation can have all journal stages passed yet report valid false.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3974]] — changed-file
- [[Evidence/S3991]] — changed-file
- [[Evidence/S3989]] — changed-file
- [[Evidence/S3988]] — changed-file

## Directed relationships

- [[Systems/repair]] — checks campaign phases and owner postconditions (`E318`)
- [[Systems/installedowner]] — can delegate the installed stage through owner configuration (`E319`)
