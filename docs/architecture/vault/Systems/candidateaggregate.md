---
canonical_id: "candidateaggregate"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Candidate aggregate report publication

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Runs remaining owners and writes a report after settlements.

## Historical source state

Per-invocation stage list and counts.

## Limits and unknowns

Resumed campaign denominator excludes previously passed stages.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3988]] — changed-file

## Directed relationships

- [[Systems/candidateadmissions]] — opens and settles one stage session (`E916`)
- [[Systems/candidatedriver]] — runs sole next pending owner (`E917`)
