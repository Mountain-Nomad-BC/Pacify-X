---
canonical_id: "certificationsupplychain"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Artifact checksums SBOM and provenance fields

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Serializes artifact subject metadata and source-control fields.

## Historical source state

Checksums, file-component SBOM and provenance.

## Limits and unknowns

Git producer uses commit_sha/tree_sha; consumer reads commit/tree, producing empty values.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2860]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
