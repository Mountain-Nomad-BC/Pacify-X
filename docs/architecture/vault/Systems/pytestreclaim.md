---
canonical_id: "pytestreclaim"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Per-test temporary child reclamation boundary

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Snapshots names below an environment-declared process root and removes newly named children after each test.

## Historical source state

Baseline names, permission retries and aggregated cleanup errors.

## Limits and unknowns

Ownership is inherited from the runner marker; this hook does not independently verify a ledger receipt or root identity after yield. No cleanup executed in this audit.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S4067]] — same-file-bytes
- [[Evidence/S3220]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
