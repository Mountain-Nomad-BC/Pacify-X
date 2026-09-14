---
canonical_id: "coreadmission"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Core registry cross-validation fanout

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Checks active admission labels, contract identity/effects/hash/dependencies and broad catalog/provider/graph/corpus validators.

## Historical source state

Accumulated errors and core active count.

## Limits and unknowns

Reads more than compact startup metadata; selected malformed types can escape. Artifact admission does not execute capabilities.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2799]] — changed-file

## Directed relationships

- [[Systems/startupconfig]] — loads required startup settings (`E555`)
- [[Systems/declaredpaths]] — resolves source or installed asset availability (`E556`)
- [[Systems/schemacorpus]] — checks shipped contract corpus (`E557`)
- [[Systems/sourcecoverage]] — checks declared source-pack control coverage (`E558`)
