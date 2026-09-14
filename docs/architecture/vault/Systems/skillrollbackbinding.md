---
canonical_id: "skillrollbackbinding"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Skill rollback backup and projection restoration

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Uses signed promotion identity/current target check and old projection images to construct rollback lifecycle transaction.

## Historical source state

Restored canonical package/projections and signed rollback receipt.

## Limits and unknowns

Backup rehash not compared to original before-tree; later projection changes become rollback transaction before-images.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3042]] — same-file-bytes

## Directed relationships

- [[Systems/skilllifecyclejournal]] — prepares rollback as another forward transaction (`E647`)
