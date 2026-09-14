---
canonical_id: "studiodraftdispatch"
kind: system
layer: acquisition
currentness: changed-file
runtime_observed: false
certified: false
---
# Typed draft graph layout and authority handoff

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Builds exact immutable revision inputs and delegates to relevant controller.

## Historical source state

Candidate/revision publication result.

## Limits and unknowns

Top-level proof gate separate; source tokens/allocation and lower owner checks still required.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3105]] — changed-file
- [[Evidence/S3099]] — changed-file

## Directed relationships

- [[Systems/agent]] — publishes candidate through agent controller (`E875`)
- [[Systems/workflowpublish]] — publishes workflow immutable revision (`E876`)
- [[Systems/skillstudio]] — stages admitted source package (`E877`)
