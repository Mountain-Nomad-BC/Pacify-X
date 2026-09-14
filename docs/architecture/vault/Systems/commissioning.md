---
canonical_id: "commissioning"
kind: system
layer: scope
currentness: changed-file
runtime_observed: false
certified: false
---
# Scaffold proposal and project adoption

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Builds expected controls, profiles and skill metadata, classifies collisions and publishes missing scaffold.

## Historical source state

File plan, adoption and optional map.

## Limits and unknowns

Reads skill bodies to hash metadata; saved inventory may be stale; no project-wide transaction.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1929]] — changed-file
- [[Evidence/S1925]] — changed-file

## Directed relationships

- [[Systems/projecttemplates]] — generates management controls (`E593`)
- [[Systems/intakeinventory]] — uses saved or fresh existing inventory (`E594`)
- [[Systems/commissionreceipt]] — binds resulting artifacts to event (`E595`)
- [[Systems/profiledecl]] — copies supplied profile declarations (`E602`)
