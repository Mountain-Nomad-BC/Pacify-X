---
canonical_id: "workflow"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Workflow Studio DAG runtime

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Validates typed node/edge contracts, selects ready conflict-free batches, executes adapters and records branch and lifecycle outcomes.

## Historical source state

Workflow revisions, admitted plans, node approvals, checkpoints and run receipts.

## Limits and unknowns

A node backed only by a declaration is not runnable; branch disabling, timeout and cancellation remain explicit.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3301]] — changed-file
- [[Evidence/S3296]] — changed-file
- [[Evidence/S3294]] — changed-file

## Directed relationships

- [[Systems/scheduler]] — selects bounded nonconflicting batches (`E042`)
- [[Systems/supervisor]] — supervises node processes (`E046`)
- [[Systems/detachedworker]] — launches owned durable workflow worker (`E185`)
- [[Systems/workflowadapters]] — executes signed closed adapter tasks (`E188`)
- [[Systems/revisionpublish]] — publishes prepared workflow revision (`E237`)
- [[Systems/workflowpublish]] — saves and admits workflow definition (`E479`)
- [[Systems/workflowbatch]] — runs dependency-ready batches (`E482`)
- [[Systems/studiolaunch]] — launches detached session for start (`E489`)
- [[Systems/dagvalidation]] — offers declarative contract validation (`E528`)
