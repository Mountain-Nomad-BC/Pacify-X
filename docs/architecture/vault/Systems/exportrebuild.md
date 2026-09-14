---
canonical_id: "exportrebuild"
kind: system
layer: release
currentness: changed-file
runtime_observed: false
certified: false
---
# Candidate projection rebuild

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Rebuilds wrappers, indexes, helper certification, ownership, dependencies and final source identity.

## Historical source state

Sequential generated projection writes under reconciliation lock.

## Limits and unknowns

Writes are not a group transaction; exact helper certification runs during rebuilding.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3613]] — changed-file

## Directed relationships

- [[Systems/exactharness]] — runs exact helper certification during projection rebuild (`E1175`)
- [[Systems/exportcertify]] — precedes governed candidate checks (`E1176`)
- [[Systems/templatebyteprojection]] — copies wrapper and pack owners first (`E1185`)
- [[Systems/profilebyteprojection]] — copies commissioned profile projections (`E1186`)
- [[Systems/activehashreconcile]] — rehashes active implementations before discovery indexes (`E1187`)
- [[Systems/declaredtoolreconcile]] — writes target reference and index outputs before discovery (`E1188`)
- [[Systems/contractownerbuilder]] — writes regenerated contract ownership (`E1189`)
- [[Systems/proofmatrixbuilder]] — writes control proof plan (`E1190`)
- [[Systems/countinventorybuilder]] — writes static count declarations (`E1191`)
