---
canonical_id: "workflowpublish"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Workflow revision publication and admission

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Separates legacy record save from locked full-layout exact-tree publication and signed runnable admission.

## Historical source state

Immutable creation receipt, layout/source identity and mutable admission receipt.

## Limits and unknowns

Dry-run path can create record via generic writer. Full publication converts cleanup errors after commit into bounded warnings; lock-exit errors remain separate.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3299]] — changed-file
- [[Evidence/S3295]] — changed-file
- [[Evidence/S3301]] — changed-file

## Directed relationships

- [[Systems/studiophys]] — publishes exact revision tree without replacement (`E480`)
- [[Systems/studioauthority]] — resolves authority and signs admission (`E481`)
