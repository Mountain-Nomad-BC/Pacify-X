---
canonical_id: "agentpreflight"
kind: system
layer: governance
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Agent structural preflight and signed admission

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Checks selected built-in structural cases, signs preflight, resolves current binding/grant closure and signs admission against exact record revision.

## Historical source state

Preflight passed/runtime_ready fields and signed admission authority hashes.

## Limits and unknowns

Memory/handoff resolution is excluded from admission_ready and checked later at runtime preview. Structural checks do not invoke an agent workload; launch rechecks record and authority, not instruction bytes.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1587]] — same-file-bytes

## Directed relationships

- [[Systems/agenthostcompletion]] — revalidates authority before host preparation (`E420`)
- [[Systems/agentworkerpublication]] — revalidates admission before owned worker launch (`E421`)
- [[Systems/agentcallback]] — resolves governed preview before plan execution (`E422`)
