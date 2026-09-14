---
canonical_id: "exhaustiveselectors"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Control locator and semantic matching

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Resolves explicit CSS or ranks visible candidate text and attributes.

## Historical source state

First matching action or semantic candidate above threshold.

## Limits and unknowns

Substring score and broad selectors can alias unrelated state; row requires an identity-like key rather than exact row identity.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S582]] — changed-file
- [[Evidence/S547]] — changed-file
- [[Evidence/S583]] — changed-file

## Directed relationships

- [[Systems/exhaustiveinteraction]] — supplies first or ranked DOM element (`E1551`)
