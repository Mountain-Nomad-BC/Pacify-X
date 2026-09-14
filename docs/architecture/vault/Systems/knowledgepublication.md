---
canonical_id: "knowledgepublication"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Canonical knowledge revision and head commit

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Checks approval, unchanged canonical base and exact source/evidence snapshots before publishing canonical revision and head.

## Historical source state

Signed immutable revision then canonical head then promoted proposal event/head.

## Limits and unknowns

Recover rolls forward a signed revision; late actor validation and separate publications expose intermediate states.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2294]] — changed-file
- [[Evidence/S2297]] — changed-file

## Directed relationships

- [[Systems/decaypublication]] — provides promoted proposal and unchanged current head (`E663`)
