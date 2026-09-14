---
canonical_id: "topologydecl"
kind: system
layer: governance
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Declared effect gates and rollback owners

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Validates nine effect rows and statically checks referenced owner symbols.

## Historical source state

Resolved declaration or errors.

## Limits and unknowns

Symbol existence and vector-file presence do not prove invocation or rollback.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1621]] — same-file-bytes

## Directed relationships

- [[Systems/duplicatelint]] — names scanner as bypass detector (`E630`)
