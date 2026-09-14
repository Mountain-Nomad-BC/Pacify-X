---
canonical_id: "transfer"
kind: system
layer: scope
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Cross-project transfer boundary

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Authorizes explicitly scoped transfer packages with independently resolved evidence and origin/target isolation.

## Historical source state

Transfer package, scope envelope and trusted evidence references.

## Limits and unknowns

Cross-project reuse requires an explicit transfer decision, not a shared index shortcut.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2679]] — same-file-bytes

## Directed relationships

- [[Systems/streams]] — authorizes cross-project handler (`E019`)
