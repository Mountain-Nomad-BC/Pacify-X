---
canonical_id: "dashboardstudiocompile"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Browser AgentSpec and typed workflow editing

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Builds graph/ports/authority declarations, validates locally and projects immutable save payload.

## Historical source state

Candidate specification, graph layout and canonical JSON editor buffer.

## Limits and unknowns

Local preflight and declaration state do not authorize runtime execution; JSON buffer requires explicit Apply.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S454]] — same-file-bytes

## Directed relationships

- [[Systems/dashboardproofresponses]] — submits immutable save and tracks disposition (`E1506`)
- [[Systems/dashboardrunresponse]] — starts exact revision from ephemeral run form (`E1510`)
- [[Systems/dashboardcssrules]] — applies editor scale and layout (`E1515`)
