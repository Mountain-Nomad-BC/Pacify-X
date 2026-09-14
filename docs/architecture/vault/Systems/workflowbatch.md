---
canonical_id: "workflowbatch"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Dependency-ready workflow batch selection

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Selects lexical ready nodes, serializes approvals and overlapping exclusive scope claims, and runs at most four workers per batch.

## Historical source state

Batch outcomes and deterministic checkpoint ordering.

## Limits and unknowns

Authority claims cached once; per-attempt authority re-resolved later. Lexical scope matching is local to this execution, not cross-run claim ownership.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3296]] — changed-file
- [[Evidence/S3297]] — changed-file

## Directed relationships

- [[Systems/workflowattempt]] — executes selected nodes and waits for batch (`E483`)
- [[Systems/workflowcheckpoint]] — checkpoints settled outcomes before failure handling (`E487`)
