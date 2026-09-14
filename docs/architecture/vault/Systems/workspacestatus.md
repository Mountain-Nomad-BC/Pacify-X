---
canonical_id: "workspacestatus"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Workspace status and composed health

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Checks bindings, projections and pending intents; optionally project checks and memory/integration smoke.

## Historical source state

Workspace/current lease and memory/integration health.

## Limits and unknowns

Full scans and separate reads; optional source root controls project integrity depth.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3344]] — changed-file
- [[Evidence/S3343]] — changed-file

## Directed relationships

- [[Systems/workspaceprojection]] — checks registry and active root projection agreement (`E590`)
- [[Systems/workspacememory]] — composes vault index and queue health (`E591`)
