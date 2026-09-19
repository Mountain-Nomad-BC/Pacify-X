---
canonical_id: "skilldeclarative"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Skill declarative validation and effect hints

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Checks package metadata, file presence/parse/text assertions, declared effects and selected secret patterns.

## Historical source state

Signed validation receipt and per-check results.

## Limits and unknowns

No execution of arbitrary skill scripts; effect detection is lexical/AST heuristic.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3044]] — changed-file
- [[Evidence/S3050]] — changed-file
- [[Evidence/S3048]] — changed-file

## Directed relationships

- [[Systems/skilltreeidentity]] — compares current payload to saved tree identity (`E639`)
