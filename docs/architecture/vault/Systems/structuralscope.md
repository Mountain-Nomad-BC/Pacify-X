---
canonical_id: "structuralscope"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Structural audit bounded source scope

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Walks selected source with budgets and excludes retained/derived custody and links.

## Historical source state

Selected file tuple for duplicate checks.

## Limits and unknowns

Other subchecks use separate scans; this is not all-files operational audit.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3066]] — changed-file

## Directed relationships

- [[Systems/structuralduplicates]] — supplies selected source paths (`E1142`)
