---
canonical_id: "fleetsessionstate"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Persistent fleet session projection

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Maintains project/agent/session registry and sealed current state.

## Historical source state

Six-state coordinator API; constructor calls found in tests.

## Limits and unknowns

No demonstrated production auto-wiring, unregister or closed state.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1527]] — changed-file

## Directed relationships

- [[Systems/fleetreadiness]] — checks new and registered participants (`E950`)
- [[Systems/walcommit]] — persists sealed state and registry (`E953`)
