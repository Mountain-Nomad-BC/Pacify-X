---
canonical_id: "hosttoolinputpolicy"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Host tool input scope and declared effect policy

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Allows only read/inspect/query/observe grants, closed cost/egress and physically scoped target strings.

## Historical source state

Sanitized input and validated target pointers.

## Limits and unknowns

Depth greater than eight returns input unchanged; declared policies do not sandbox tool implementation.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1119]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
