---
canonical_id: "releasefixturecopy"
kind: system
layer: release
currentness: changed-file
runtime_observed: false
certified: false
---
# Classified release-test source materialization

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Copies selected product, packaged evidence and caller extras after classification.

## Historical source state

Fixture count and pre-copy product/harness hashes.

## Limits and unknowns

No postcopy digest comparison or all-input prevalidation; later failure leaves earlier copies.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2808]] — changed-file

## Directed relationships

- [[Systems/releaseclassify]] — selects product paths from initial classification (`E820`)
