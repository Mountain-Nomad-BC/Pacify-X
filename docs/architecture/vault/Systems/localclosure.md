---
canonical_id: "localclosure"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Local model stop and absent-process recovery

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Requires explicit boolean for stop/unload, chooses in-memory manager or persisted supervisor closure and records disposition.

## Historical source state

Stopped or recovered_absent event; model file retained.

## Limits and unknowns

Status is not live health. Recovery root-process absence does not itself enumerate descendants; event publication remains separate from resource closure.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2347]] — changed-file
- [[Evidence/S2344]] — changed-file

## Directed relationships

- [[Systems/supervisionclose]] — reconciles persisted process when handle absent (`E523`)
