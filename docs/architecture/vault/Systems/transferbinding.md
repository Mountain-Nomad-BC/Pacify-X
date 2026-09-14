---
canonical_id: "transferbinding"
kind: system
layer: governance
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Transfer receipt and imported content binding

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Resolves four signed scoped accepted receipts before copying a workspace-contained file.

## Historical source state

Transfer decision and copied-byte hash event.

## Limits and unknowns

Receipts bind transfer/project IDs; no byte digest or actual project path membership bound to them.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2681]] — same-file-bytes
- [[Evidence/S2636]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
