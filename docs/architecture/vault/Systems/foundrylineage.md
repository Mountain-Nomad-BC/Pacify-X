---
canonical_id: "foundrylineage"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Foundry candidate lineage digest

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Checks source SHA/citation presence, candidate digest and domain-separated digest label.

## Historical source state

FoundryCandidateSkill with unknown effects and candidate-only authority.

## Limits and unknowns

Lineage signature is unkeyed hash; calculation export references incompatible producer fields.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2190]] — changed-file
- [[Evidence/S2189]] — changed-file

## Directed relationships

- [[Systems/foundrydraftobject]] — validates before explicit accept or reject (`E691`)
