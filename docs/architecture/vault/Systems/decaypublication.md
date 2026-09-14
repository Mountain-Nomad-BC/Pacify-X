---
canonical_id: "decaypublication"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Canonical suspect status before learning transition

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Marks the currently promoted canonical head suspect and records declared dependent invalidation.

## Historical source state

Canonical head write followed by learning transition.

## Limits and unknowns

Direct method checks approved/actor/CAS only at the later transition; Studio wrapper supplies approved host proof first.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2292]] — changed-file

## Directed relationships

- [[Systems/learningjournal]] — writes suspect head before transition validation (`E664`)
- [[Systems/dependencycone]] — computes declared downstream invalidation metadata (`E665`)
