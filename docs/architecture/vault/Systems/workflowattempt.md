---
canonical_id: "workflowattempt"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Workflow supervised attempt and retry boundary

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Signs current node task, registers request path, launches deadline-bound worker, reclaims task and collects bounded output/process receipt.

## Historical source state

Node outputs and attempt/cleanup/process receipts.

## Limits and unknowns

Retries repeat same input and consumed approval without new-evidence gate. Output contract validation occurs after retry loop. Cleanup exception can mask earlier task error.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3294]] — changed-file
- [[Evidence/S3291]] — changed-file

## Directed relationships

- [[Systems/supervisebudget]] — runs each attempt under process supervisor (`E484`)
- [[Systems/workflowadapter]] — sends signed request to closed worker (`E485`)
- [[Systems/resourcereclaim]] — reclaims request directory before response use (`E486`)
