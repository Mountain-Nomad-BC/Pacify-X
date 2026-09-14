---
canonical_id: "iwplugin"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Installed plugin mutation and recovery chain

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Installs v1, updates v2, inspects conflict, uninstalls, rolls back and restores absent fixture.

## Historical source state

Version, pending/reconciled receipt, restart and cleanup observations.

## Limits and unknowns

Version-only reconstruction is not terminal custody/tree proof; failure cleanup may uninstall a preexisting fixture.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S649]] — same-file-bytes

## Directed relationships

- [[Systems/iwpluginconfirm]] — binds preview token and confirmation (`E1594`)
- [[Systems/iwframe]] — reconstructs full workbench and version (`E1596`)
