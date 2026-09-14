---
canonical_id: "integrations"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Integration contract and handler registry

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Validates integration schemas, unique identities and importable handlers/healthchecks, optionally executing active smoke checks.

## Historical source state

Integration identity, loading rule, active denominator and smoke_tested flag.

## Limits and unknowns

A resolvable handler and optional self-check do not prove an external service is connected or production-operational.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2271]] — same-file-bytes

## Directed relationships

- [[Systems/catalog]] — registers bounded handler availability (`E172`)
- [[Systems/schedulesimulation]] — checks one simulated noop task (`E411`)
- [[Systems/retrievalcore]] — checks one public fixture retrieval (`E412`)
- [[Systems/metacognition]] — checks layer metadata counts and references (`E413`)
