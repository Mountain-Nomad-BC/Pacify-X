---
canonical_id: "attachmentidentity"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Model attachment construction and validation

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Builds content-derived model identity and optionally hashes local GGUF artifact; validates decoded attachment self-consistency.

## Historical source state

Artifact/revision/privacy/authority/benchmark and fallback identity bindings.

## Limits and unknowns

Constructor local path/suffix and fallback revision checks are not all repeated by validator. Remote bytes are not fetched; exact revision rejects a small floating-label set.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2428]] — changed-file
- [[Evidence/S2431]] — changed-file

## Directed relationships

- [[Systems/planidentity]] — binds model and ranking hashes into plan (`E512`)
