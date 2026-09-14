---
canonical_id: "taskdag"
kind: system
layer: scope
currentness: changed-file
runtime_observed: false
certified: false
---
# Coordination task DAG and scope ordering

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Rejects missing dependencies, cycles and unordered overlapping claim targets before recording a parallel plan.

## Historical source state

Normalized task scopes, transitive dependency closure, active plan and task records.

## Limits and unknowns

A valid DAG establishes ordering and ownership intent. The createParallelPlan handler does not spawn workers.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S945]] — changed-file

## Directed relationships

- [[Systems/tasklease]] — provides dependencies and declared claim scopes (`E217`)
- [[Systems/coordpublish]] — commits plan through shared state transition (`E231`)
