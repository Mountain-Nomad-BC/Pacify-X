---
canonical_id: "cachewalkcustody"
kind: system
layer: scope
currentness: changed-file
runtime_observed: false
certified: false
---
# Python cache discovery and custody exclusions

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Discovers cache directories and loose bytecode through a bounded fail-closed walker.

## Historical source state

Directory targets, loose files and per-file inventory hashes.

## Limits and unknowns

Walk skips links and external custody, but later whole-directory moves can carry children excluded from inventory.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3665]] — same-file-bytes
- [[Evidence/S1648]] — changed-file

## Directed relationships

- [[Systems/cachemovepublication]] — passes selected targets and inventory (`E1432`)
