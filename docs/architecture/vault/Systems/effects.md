---
canonical_id: "effects"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Effect contracts and signed grants

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Checks declared effects, approval, idempotency, budgets and signed scope-bound grants before non-read execution.

## Historical source state

Effect grant, signature, trust policy and authorization decision.

## Limits and unknowns

Signed-grant validation is triggered by execution_contract.NON_READ_EFFECTS, a seven-name set that differs from operation_authority mutation aliases; inspect the exact requested effect spelling.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2135]] — changed-file
- [[Evidence/S2046]] — changed-file

## Directed relationships

- [[Systems/orchestrator]] — gates handler activation (`E028`)
- [[Systems/provider]] — binds allowed egress and authority (`E039`)
