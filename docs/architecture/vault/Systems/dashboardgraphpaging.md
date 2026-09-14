---
canonical_id: "dashboardgraphpaging"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Browser graph request and page accumulation

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Queries bounded pages, matches response ID and merges full graph nodes/edges.

## Historical source state

Accumulated graph and page continuation state.

## Limits and unknowns

Twelve-second bound applies per request; no aggregate page cap, cursor progress check or snapshot identity check in merge.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S371]] — same-file-bytes
- [[Evidence/S415]] — same-file-bytes

## Directed relationships

- [[Systems/dashboardgraphgeometry]] — renders matching accumulated result (`E1511`)
