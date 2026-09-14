---
canonical_id: "stateclass"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Classified authoritative-state loading

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Loads registered state kinds; marks invalid derived data rebuild_required and preserves/quarantines corrupt authoritative data before raising.

## Historical source state

Classification, valid data or rebuild-required result, and authoritative quarantine receipt.

## Limits and unknowns

This owner does not invent empty authoritative fallback. Other metadata loaders have different tolerance rules.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1619]] — changed-file

## Directed relationships

- [[Systems/recovery]] — requires authoritative custody or derived rebuild (`E164`)
- [[Systems/classifiedload]] — dispatches classified parse behavior (`E766`)
