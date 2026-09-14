---
canonical_id: "agenttypedgraph"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Closed typed Agent Studio topology

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Validates 9 required and up to 3 optional nodes with exact ports and fixed edges.

## Historical source state

Canonical graph projected from AgentSpec.

## Limits and unknowns

Graph describes configuration dependencies; edges do not grant or execute effects.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1516]] — changed-file
- [[Evidence/S1518]] — changed-file

## Directed relationships

- [[Systems/agentspeccompile]] — compiles fixed config topology (`E944`)
