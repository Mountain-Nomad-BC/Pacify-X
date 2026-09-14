---
canonical_id: "lazytransaction"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Lazy skill prepare and retained-context commit

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Reads admitted descriptor dependency bundle and requested references then atomically updates active in-memory set.

## Historical source state

HydratedSkill and active byte/count footprint.

## Limits and unknowns

Full reads precede retained limits; catalog adapter leaves dependencies empty; cache keyed only ID.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2325]] — changed-file
- [[Evidence/S2324]] — changed-file

## Directed relationships

- [[Systems/declaredpaths]] — applies its own resolved body containment (`E610`)
