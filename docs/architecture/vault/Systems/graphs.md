---
canonical_id: "graphs"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Owned graph projections

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Builds capability/I-O/dependency/system graphs and tracks graph ownership, consumers and invalidation rules.

## Historical source state

Derived registry graphs and source revision manifests.

## Limits and unknowns

Some graph relationships encode declarations. They must be cross-checked against handlers before calling them executions.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2221]] — same-file-bytes
- [[Evidence/S1494]] — same-file-bytes
- [[Evidence/S3188]] — same-file-bytes

## Directed relationships

- [[Systems/router]] — supports bounded relationship expansion (`E026`)
- [[Systems/dashboard]] — serves bounded graph pages (`E092`)
- [[Systems/cognav]] — supplies unified cognitive metadata (`E122`)
- [[Systems/graphprojection]] — builds canonical projections (`E526`)
- [[Systems/typepaths]] — offers type compatibility search (`E527`)
