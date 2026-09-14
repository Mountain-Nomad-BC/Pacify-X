---
canonical_id: "cligroupexecution"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# CLI parallel and serial group scheduler

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Runs parallel-safe groups then serial groups, writing each receipt and refreshing completion projection.

## Historical source state

Sorted group results and selected-count validity.

## Limits and unknowns

No per-group in-progress invalidation; an uncaught worker exception interrupts later scheduling.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1777]] — changed-file

## Directed relationships

- [[Systems/testprocesscustody]] — executes each selected group (`E1379`)
- [[Systems/testreceiptstatus]] — publishes group receipts and returns status (`E1380`)
