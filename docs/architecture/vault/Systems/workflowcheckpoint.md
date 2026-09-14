---
canonical_id: "workflowcheckpoint"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Workflow checkpoint resume and terminal publication

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Retains successful/skipped/continued node results, handles lifecycle requests after batch settlement and resumes exact run/input/revision identity.

## Historical source state

Signed durable head/checkpoint and separately written run receipt.

## Limits and unknowns

Finalizing cancel/stop directly publishes cancelled without worker-exit check. Normal detached closure uses observer; receipt publication follows state transition.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3297]] — changed-file
- [[Evidence/S3298]] — changed-file

## Directed relationships

- [[Systems/durablepublisher]] — transitions signed run state (`E488`)
- [[Systems/workflowtracebrowser]] — offers durable checkpoint receipts for display (`E1072`)
