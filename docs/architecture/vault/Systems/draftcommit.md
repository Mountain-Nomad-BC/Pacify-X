---
canonical_id: "draftcommit"
kind: system
layer: host
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Studio draft save and result delivery

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Authenticates version allocation and source lineage, confirms a concrete save, materializes skill input, admits its exact tree and classifies the backend commit receipt before notifying the originating webview.

## Historical source state

Owner-bound allocation proof, source token/tree hash, immutable draft receipt, delivery/cleanup warnings.

## Limits and unknowns

A committed save and a delivered success message are different outcomes. An invalid commit receipt yields commit-outcome-unverified rather than inventing success.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1290]] — same-file-bytes

## Directed relationships

- [[Systems/bridge]] — rechecks versions and issues exact save calls (`E223`)
- [[Systems/studioauth]] — consumes owner-bound allocation before save (`E224`)
- [[Systems/ui]] — reports committed unverified or delivery-warning outcome (`E225`)
- [[Systems/studiopackage]] — receives materialization and reclamation callbacks (`E304`)
