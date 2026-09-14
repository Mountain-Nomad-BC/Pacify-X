---
canonical_id: "extensionpreviewtokens"
kind: system
layer: governance
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Lifecycle previews and exact target checks

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Issues short-lived one-use previews, then rechecks target state before native handoff.

## Historical source state

Five-minute in-memory preview map with capacity 64.

## Limits and unknowns

No operation mutex or origin binding; capacity pruning runs on execute too.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1135]] — same-file-bytes

## Directed relationships

- [[Systems/extensionnativeeffect]] — consumes and validates preview before command (`E1049`)
- [[Systems/extensionrollbackcustody]] — retains uninstall record before host effect (`E1051`)
