---
canonical_id: "semanticprojection"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Cheap semantic catalog projection

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Compiles catalog, contract, body-description, alias and workflow-membership fields into deterministic semantic profiles and hashes without runtime skill hydration.

## Historical source state

Profile, contract and body revisions, metadata-only records and aggregate projection revision.

## Limits and unknowns

The builder reads source bodies to extract descriptions; metadata-only describes the resulting query surface, not an absence of build-time body reads.

## Historical suggested evolution

Skill promotion can rebuild this cheap projection from unpublished overlay bytes so later discovery sees the new metadata.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3008]] — same-file-bytes
- [[Evidence/S2798]] — changed-file
- [[Evidence/S1679]] — same-file-bytes

## Directed relationships

- [[Systems/catalog]] — supplies metadata profiles and revisions (`E227`)
