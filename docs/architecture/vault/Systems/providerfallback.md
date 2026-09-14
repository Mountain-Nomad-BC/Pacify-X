---
canonical_id: "providerfallback"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Single same-provider fallback attempt

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

On ProviderInvocationError checks admitted fallback, same provider and budget allowlist; invokes with suffixed identity and new reservation.

## Historical source state

Primary failed accounting plus independently budgeted fallback receipt.

## Limits and unknowns

Replaces adapter_id/invocation_id only; primary model/revision/attachment remain. Immutable fallback row metadata is checked for shape/order but not substituted into the request.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2729]] — same-file-bytes
- [[Evidence/S2734]] — same-file-bytes

## Directed relationships

- [[Systems/budget]] — checks allowlist and reserves another invocation (`E403`)
