---
canonical_id: "workspacerecall"
kind: system
layer: memory
currentness: changed-file
runtime_observed: false
certified: false
---
# Workspace recall and caller-scoped rank fusion

[[Layers/memory]] · [[Views/Full_Architecture]]

## Purpose

Requires active project lease/actor then sends eligible canonical records into lexical, supplied semantic/graph, fixed-binding and recent ranking.

## Historical source state

Ranked memory rows, rejection reasons and selection identity.

## Limits and unknowns

This route does not invoke vault.search or its exact semantic key/SimHash selector. Upstream vault prefilter and downstream ranker apply different scopes; caller scores are optional.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3309]] — changed-file
- [[Evidence/S2361]] — changed-file

## Directed relationships

- [[Systems/memorycontext]] — supplies selected ranked records for bounded assembly (`E418`)
