---
canonical_id: "mapcorpus"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Project source corpus and bounded traversal

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Selects default/sensitive/caller/Git-visible paths, inventories metadata and computes full source hashes before bounded text parsing.

## Historical source state

Sorted source inventory and recorded exclusion/Git policy.

## Limits and unknowns

Git failure broadens to explicit default exclusions; file/depth/stat bytes do not bound every directory allocation or later growing file read.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2651]] — same-file-bytes
- [[Evidence/S2648]] — same-file-bytes
- [[Evidence/S1651]] — changed-file

## Directed relationships

- [[Systems/mapfacts]] — supplies hash and bounded text (`E546`)
