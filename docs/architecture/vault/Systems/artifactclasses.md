---
canonical_id: "artifactclasses"
kind: system
layer: release
currentness: changed-file
runtime_observed: false
certified: false
---
# Release tree artifact classification

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Classifies product, control-plane, evidence, audit, intermediate and unclassified paths with bounded tree traversal and symlink rejection.

## Historical source state

Class counts, full-tree errors, product errors and product digest.

## Limits and unknowns

product_valid and valid have different denominators. Control/evidence bytes are excluded from the product digest; the digest alone does not bind every repository file.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2807]] — changed-file

## Directed relationships

- [[Systems/walklimits]] — enumerates the classified tree within hard bounds (`E312`)
- [[Systems/releaseclassify]] — implements source classification (`E819`)
