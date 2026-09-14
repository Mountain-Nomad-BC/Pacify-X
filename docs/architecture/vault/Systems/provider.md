---
canonical_id: "provider"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Provider invocation gateway

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Provides budgeted invocation and an optional immutable-policy wrapper; these are distinct entry points and are not a universal model-execution funnel.

## Historical source state

Provider request, invocation identity, output hash and budget receipt.

## Limits and unknowns

Direct invoke enforces adapter registry and budget; execute_provider_request adds supplied policy comparisons. Separate host and Python agent routes do not automatically enter this gateway.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2739]] — same-file-bytes
- [[Evidence/S2738]] — same-file-bytes
- [[Evidence/S1170]] — same-file-bytes

## Directed relationships

- [[Systems/telemetry]] — emits correlated provider events (`E048`)
- [[Systems/evidence]] — returns exact output and budget receipt (`E049`)
- [[Systems/eventbushead]] — checks current publication ancestry (`E758`)
- [[Systems/ollamastream]] — has host-registered local transport implementation (`E1077`)
