---
canonical_id: "fleetsessionreplay"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Fleet canonical event reconstruction

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Matches persisted anchor in global bus suffix and applies later validated session events.

## Historical source state

May repair projection while reading status.

## Limits and unknowns

Requires existing registry/state and anchor in last 10000 global events.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1533]] — changed-file
- [[Evidence/S1531]] — changed-file

## Directed relationships

- [[Systems/eventbusreplay]] — requests bounded global suffix (`E954`)
- [[Systems/fleetsessionstate]] — repairs lagging local projection (`E955`)
