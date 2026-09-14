---
canonical_id: "effectinventory"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Static Python effect-surface inventory

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Walks bounded source, identifies selected process/network/filesystem call spellings, records source-located policy ownership and checks registry freshness, timeout/shell rules and destructive-owner exceptions.

## Historical source state

AST call records, source locators, timeout metadata and registry comparison failures.

## Limits and unknowns

This scan targets Python and recognized call spellings. It is not a JavaScript/network runtime observer or proof of every dynamic effect.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2049]] — changed-file
- [[Evidence/S2050]] — changed-file

## Directed relationships

- [[Systems/effects]] — supplies static effect-location ownership evidence (`E238`)
