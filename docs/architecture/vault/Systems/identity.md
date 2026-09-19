---
canonical_id: "identity"
kind: system
layer: release
currentness: changed-file
runtime_observed: false
certified: false
---
# Exact engine and product identity

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Hashes the selected CPU-authoritative file boundary and materializes a clean release product excluding specified mutable state and generated artifacts.

## Historical source state

Per-file identities, tree digest and copied clean-product boundary.

## Limits and unknowns

Different identity builders have different declared exclusions; Git HEAD alone is not an identity for mutable working-tree contents.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2054]] — changed-file
- [[Evidence/S2053]] — changed-file
- [[Evidence/S2816]] — changed-file
- [[Evidence/S2958]] — changed-file
- [[Evidence/S2925]] — changed-file
- [[Evidence/S2807]] — changed-file
- [[Evidence/S3264]] — same-file-bytes

## Directed relationships

- [[Systems/package]] — defines exact materialized product boundary (`E194`)
- [[Systems/artifactclasses]] — classifies mutable and blocking changed paths (`E311`)
- [[Systems/currentindex]] — indexes exact filtered source and artifact evidence (`E498`)
