---
canonical_id: "orchestrator"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Bounded single-capability orchestrator

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Selects one admitted capability, checks inputs and authority, resolves one handler, assembles evidence and verifies outcomes.

## Historical source state

Task checkpoints, selected handler, evidence package and result.

## Limits and unknowns

Current run path does not pass the signed-grant arguments required by enforce for non-read effects.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2588]] — changed-file

## Directed relationships

- [[Systems/evidence]] — assembles handler claims and receipts (`E029`)
- [[Systems/verify]] — evaluates postconditions (`E030`)
- [[Systems/recovery]] — records checkpoints and failures (`E031`)
- [[Systems/operationcompose]] — checks caller owner and authority fields (`E466`)
- [[Systems/executionenvelope]] — enforces selected manifest and direct policy (`E467`)
- [[Systems/compatcompletion]] — runs one injected handler and assembles result (`E474`)
- [[Systems/coreadmission]] — validates registries before task handling (`E554`)
