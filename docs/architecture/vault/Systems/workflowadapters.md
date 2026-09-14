---
canonical_id: "workflowadapters"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Closed workflow node adapters

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Revalidates signed task, executor, binding and grant hashes, executes one of a closed adapter set and evaluates declared validation checks.

## Historical source state

Node liveness, typed outputs, validation checks and consumed approval metadata.

## Limits and unknowns

The inspected standalone worker admits identity, increment, double, fail and sleep adapters. Other capability families are not implicitly runnable through this worker.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3307]] — same-file-bytes
- [[Evidence/S3306]] — same-file-bytes

## Directed relationships

- [[Systems/studioauth]] — rechecks task and grant identities (`E189`)
