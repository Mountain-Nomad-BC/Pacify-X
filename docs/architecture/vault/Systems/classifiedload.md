---
canonical_id: "classifiedload"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Classified JSON parse and validation

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Loads declared artifact class, parses object and invokes optional validator.

## Historical source state

Valid data, rebuild_required or authoritative-state exception.

## Limits and unknowns

Successful reads do not enforce allowed-root containment; validator failures can trigger quarantine.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1619]] — changed-file

## Directed relationships

- [[Systems/corruptstatecustody]] — moves available corrupt authoritative file (`E767`)
