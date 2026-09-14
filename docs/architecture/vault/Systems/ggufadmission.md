---
canonical_id: "ggufadmission"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# GGUF metadata and artifact admission

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Checks contained resolved model path, parses bounded metadata prefix and hashes complete file with before/after identity comparison.

## Historical source state

ModelAdmission with metadata, hash, filesystem identity and compatibility reasons.

## Limits and unknowns

Compatibility is architecture membership plus context presence; tensor validity, memory feasibility and runtime support are not demonstrated.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2348]] — changed-file
- [[Evidence/S2342]] — changed-file

## Directed relationships

- [[Systems/localserverplan]] — supplies compatibility and artifact identity (`E519`)
