---
canonical_id: "agenteditgraph"
kind: system
layer: reasoning
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Agent editor closed topology and working edits

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Projects fixed typed AgentSpec graph and supports bounded optional nodes and canonical edge edits.

## Historical source state

Working graph and candidate payload.

## Limits and unknowns

Working synchronization and explicit node edit use different edge-preservation semantics.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S321]] — same-file-bytes

## Directed relationships

- [[Systems/agenttypedgraph]] — offers typed graph to independent backend compiler (`E1040`)
