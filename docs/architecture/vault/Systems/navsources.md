---
canonical_id: "navsources"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Shared metadata across discovery sources

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Returns skill-catalog, semantic-index, cognitive-index and agency-registry search paths.

## Historical source state

Four independently invoked metadata adapters.

## Limits and unknowns

Skill adapter already incorporates semantic-index fields; agreement is not fully independent evidence.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2797]] — changed-file
- [[Evidence/S2798]] — changed-file
- [[Evidence/S2796]] — changed-file

## Directed relationships

- [[Systems/navscores]] — materializes adapters into search inputs (`E561`)
- [[Systems/routingfusion]] — supplies named metadata discovery paths (`E562`)
