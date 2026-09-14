---
canonical_id: "hosttoolinterface"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Live host tool interface and invocation receipts

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Checks registered names/object schemas, computes interface hashes and records tool call input/result hashes.

## Historical source state

In-memory started/completed/failed call receipts.

## Limits and unknowns

Hash is observed at preparation without comparison to an admitted interface digest or recheck before invocation.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1036]] — changed-file

## Directed relationships

- [[Systems/hosttoolinputpolicy]] — checks each requested call input (`E1488`)
