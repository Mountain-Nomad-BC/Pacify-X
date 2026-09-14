---
canonical_id: "hostcompletionroute"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Prepared model run and signed completion handoff

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Prepares admitted durable run, invokes host model, signs complete-host-run and refreshes UI.

## Historical source state

Prepared run, host result and backend completion receipt.

## Limits and unknowns

Initial UI publication can fail after preparation; completion/refresh failure can follow model effect; terminal result lacks original requestId.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1022]] — changed-file

## Directed relationships

- [[Systems/hostmodelbudget]] — executes prepared exact host model (`E1486`)
- [[Systems/agenthostcompletion]] — submits signed complete-host-run result (`E1489`)
