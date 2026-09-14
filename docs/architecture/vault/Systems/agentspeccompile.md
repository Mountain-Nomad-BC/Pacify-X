---
canonical_id: "agentspeccompile"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Agent graph to specification compiler

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Maps graph configs back to AgentSpec and checks exact equality.

## Historical source state

AgentSpec with requested bindings, contracts and lifecycle.

## Limits and unknowns

Authority/test/model IDs require their separate runtime owners.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1524]] — changed-file
- [[Evidence/S1523]] — changed-file

## Directed relationships

- [[Systems/agentgraphreceipt]] — checks equality before artifact creation (`E945`)
