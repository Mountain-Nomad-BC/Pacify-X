---
canonical_id: "candidateadmissions"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Candidate per-stage ledger sessions

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Creates admission, closes session and checkpoints after each aggregate stage.

## Historical source state

Admission and closure IDs in stage evidence.

## Limits and unknowns

No local guard-work before execution; settlement/cancellation gaps remain.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3977]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
