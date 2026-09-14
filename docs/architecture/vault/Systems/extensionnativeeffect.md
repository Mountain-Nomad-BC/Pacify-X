---
canonical_id: "extensionnativeeffect"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Native extension command and immediate observation

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Requests install/update/uninstall and immediately rereads installation inventory.

## Historical source state

Reconciled or pending host receipt.

## Limits and unknowns

Local bytes are hashed but declared package identity is not read from VSIX; no wait for reload.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1135]] — same-file-bytes

## Directed relationships

- [[Systems/physicalextensioninventory]] — observes installation immediately after native command (`E1050`)
