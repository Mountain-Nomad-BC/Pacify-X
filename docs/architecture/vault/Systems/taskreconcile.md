---
canonical_id: "taskreconcile"
kind: system
layer: scope
currentness: changed-file
runtime_observed: false
certified: false
---
# Coordination completion and reconciliation

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Requires completed task plus owning active claim, appends a reconciliation receipt, releases claims and completes the active plan when all its tasks are reconciled.

## Historical source state

Task outputs, released leases, plan completion and supplied conflict/evidence fields.

## Limits and unknowns

The receipt records conflicts_resolved and evidence supplied by the caller; this function does not perform a Git merge or independently execute acceptance tests.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S955]] — changed-file

## Directed relationships

- [[Systems/taskdag]] — completes the plan after every task reconciles (`E219`)
- [[Systems/coordpublish]] — commits reconciliation and handoff projection (`E233`)
