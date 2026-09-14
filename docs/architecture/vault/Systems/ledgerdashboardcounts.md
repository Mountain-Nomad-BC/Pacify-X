---
canonical_id: "ledgerdashboardcounts"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Ledger ownership proof and dashboard counters

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Derives control resolution, observation counts, feature-aware open count and clipped dashboard rows.

## Historical source state

Several distinct completion denominators.

## Limits and unknowns

Ownership resolved, observation typed, card operational and card closed are different predicates.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2489]] — changed-file
- [[Evidence/S2499]] — changed-file

## Directed relationships

- [[Systems/ledgercheckpointpublisher]] — embeds bounded dashboard index in head (`E1245`)
