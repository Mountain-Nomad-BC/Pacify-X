---
canonical_id: "plan"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Immutable task execution plan

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Binds a route to project/source/projection revisions, selected capabilities, effects, authority and model attachments.

## Historical source state

TaskExecutionPlan and its plan/package/source hashes.

## Limits and unknowns

A valid plan describes intended execution; it is not evidence that execution occurred.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3190]] — same-file-bytes

## Directed relationships

- [[Systems/agent]] — binds governed execution (`E032`)
- [[Systems/workflow]] — binds selected node execution (`E033`)
