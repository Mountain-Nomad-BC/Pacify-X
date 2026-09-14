---
canonical_id: "extensionrollbackcustody"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Retained uninstall history and rollback source

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Stores retained uninstall record before native command; rollback selects retained version/source.

## Historical source state

Durable host storage history and optional retained local source.

## Limits and unknowns

Storage and native effects are not atomic; latest-source map is not complete update history.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1135]] — same-file-bytes

## Directed relationships

- [[Systems/extensionnativeeffect]] — supplies retained rollback target and source (`E1052`)
