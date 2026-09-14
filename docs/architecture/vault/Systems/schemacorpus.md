---
canonical_id: "schemacorpus"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Contract fixture ownership and digest audit

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Builds smoke fixture, validates it and empty required negative, checks ownership declarations and hashes transitive schemas.

## Historical source state

Corpus digest/counts/enforcement labels and errors.

## Limits and unknowns

Same interpreter generates/verifies fixtures; references and hashes are separate reads. Owner file and test existence are not enforcement proof.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1956]] — changed-file
- [[Evidence/S1954]] — changed-file
- [[Evidence/S1955]] — changed-file

## Directed relationships

- [[Systems/schemainstance]] — uses same admitted rule interpreter for fixtures (`E559`)
