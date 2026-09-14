---
canonical_id: "bundlepxcontext"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# SDK context lost at PX instrumentation wrapper

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Wraps tool authority and activity around input-only PX handlers.

## Historical source state

Authorized input plus local correlation and lifecycle events.

## Limits and unknowns

SDK executor passes context, but wrapper accepts only input and calls handler without signal or request identity.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S839]] — changed-file
- [[Evidence/S830]] — changed-file

## Directed relationships

- [[Systems/mcproutes]] — dispatches PX input after authority (`E1622`)
