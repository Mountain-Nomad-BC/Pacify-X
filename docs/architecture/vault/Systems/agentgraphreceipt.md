---
canonical_id: "agentgraphreceipt"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Agent graph layout and compiler receipt

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Binds graph, normalized canvas layout and AgentSpec; verifier reconstructs and recompiles.

## Historical source state

Three consistent JSON artifacts.

## Limits and unknowns

Hashes are unkeyed consistency; layout identity separate from execution approval.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1520]] — changed-file
- [[Evidence/S1526]] — changed-file

## Directed relationships

- [[Systems/agent]] — verifies persisted graph on open (`E946`)
