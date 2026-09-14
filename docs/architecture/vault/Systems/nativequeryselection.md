---
canonical_id: "nativequeryselection"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Native token ranking and domain grants

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Filters requested domains, scores ID/tag/description tokens and bounds candidates.

## Historical source state

Up to three metadata candidates; exact ID returns first visible row.

## Limits and unknowns

Grant strings and admission labels are caller/registry inputs, not host authority proof.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2444]] — changed-file

## Directed relationships

- [[Systems/nativebodyhydrate]] — reselects exact ID before hydration (`E882`)
