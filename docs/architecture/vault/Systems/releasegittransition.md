---
canonical_id: "releasegittransition"
kind: system
layer: release
currentness: changed-file
runtime_observed: false
certified: false
---
# Source commit and annotated retag

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Requires explicit dirty/index path set, commits and moves existing annotated tag before applying identity.

## Historical source state

Local Git commit/tag and release identity receipt.

## Limits and unknowns

No rollback across index, commit, tag and identity writes.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S4003]] — changed-file

## Directed relationships

- [[Systems/releasecampaignidentity]] — applies identity after commit and retag (`E906`)
