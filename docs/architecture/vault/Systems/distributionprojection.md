---
canonical_id: "distributionprojection"
kind: system
layer: release
currentness: changed-file
runtime_observed: false
certified: false
---
# Source-to-wheel and source-to-sdist projection

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Expands setuptools and bounded MANIFEST directive subset into hashed source records.

## Historical source state

Artifact manifest and allowed generated paths.

## Limits and unknowns

Manifest generation follows live source reads; declaration matching is not atomic source snapshot.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2864]] — changed-file
- [[Evidence/S2869]] — changed-file

## Directed relationships

- [[Systems/distributionskillclosure]] — checks commissioned skill source coverage (`E1161`)
