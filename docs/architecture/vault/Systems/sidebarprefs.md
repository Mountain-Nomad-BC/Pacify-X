---
canonical_id: "sidebarprefs"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Sidebar workspace preference persistence

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Normalizes and stores wave/task expansion and selected provider then republishes host snapshot.

## Historical source state

WorkspaceState preference object.

## Limits and unknowns

Storage await does not serialize concurrent updates; browser toggles optimistically before host result.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1234]] — same-file-bytes
- [[Evidence/S1250]] — same-file-bytes
- [[Evidence/S1239]] — same-file-bytes

## Directed relationships

- [[Systems/sidebarprojectcalc]] — supplies normalized expansion and provider selection (`E1013`)
