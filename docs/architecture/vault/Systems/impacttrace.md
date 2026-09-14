---
canonical_id: "impacttrace"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Project call and import impact traversal

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Resolves exact target after map validation, walks call/import graphs and aggregates tests/routes/contracts/services with heuristic risk.

## Historical source state

Affected records with depth, limits and map revision.

## Limits and unknowns

Two graph budgets and uncapped initial seeds are not one global cap; reaching max depth does not mark truncated. Static edge uncertainty remains.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2643]] — changed-file
- [[Evidence/S2642]] — changed-file

## Directed relationships

- [[Systems/impactinvalidation]] — offers explicit result adaptation (`E537`)
