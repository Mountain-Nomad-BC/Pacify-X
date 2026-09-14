---
canonical_id: "skillstudio"
kind: system
layer: acquisition
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Skill Studio promotion and rollback

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Preserves originals, stages and tests drafts, admits source-bound packages and transactionally promotes or rolls back canonical skill bytes and projections.

## Historical source state

Draft/admission/promotion receipts, canonical skill directory, preserved predecessors and projection updates.

## Limits and unknowns

A Studio package and a framework-level catalog entry retain their own identities and admission paths.

## Historical suggested evolution

Promotion changes canonical skill bytes and discoverable projections; rollback restores predecessors.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3041]] — same-file-bytes
- [[Evidence/S3033]] — same-file-bytes

## Directed relationships

- [[Systems/catalog]] — updates discoverable projections (`E067`)
- [[Systems/recovery]] — preserves predecessor and rollback identity (`E068`)
- [[Systems/invalidation]] — marks heavier graph projections stale (`E128`)
- [[Systems/semanticprojection]] — rebuilds cheap metadata using unpublished overlays (`E228`)
- [[Systems/revisionpublish]] — publishes exact prepared draft revision (`E236`)
- [[Systems/projectionplan]] — records obligations for governed rebuild (`E257`)
- [[Systems/world]] — writes a staleness shape the reader does not consume (`E258`)
- [[Systems/catalogproof]] — supplies revision tree and lifecycle evidence (`E277`)
- [[Systems/maturityladder]] — evaluates generated base and caller higher evidence (`E631`)
- [[Systems/semanticbuildio]] — builds unpublished semantic after-image with overlays (`E634`)
- [[Systems/skilladmitreceipt]] — verifies admission before preparing new promotion (`E641`)
- [[Systems/skillprojectionafter]] — constructs projection bytes for candidate tree (`E642`)
- [[Systems/skilllifecyclejournal]] — prepares and applies promotion transaction (`E644`)
- [[Systems/skillrollbackbinding]] — resolves signed promotion for approved rollback (`E646`)
