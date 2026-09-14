---
canonical_id: "exportselection"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Clean export source selection

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Selects repository source and retained commissioning/test authority for copied candidate.

## Historical source state

Sorted candidate input list.

## Limits and unknowns

Selection is separate from stable source snapshot and Git archive membership.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3646]] — changed-file

## Directed relationships

- [[Systems/exportfreeze]] — copies selected files and emits staged manifest (`E1173`)
