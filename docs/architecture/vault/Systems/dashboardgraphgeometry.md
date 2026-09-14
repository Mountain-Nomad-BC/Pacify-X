---
canonical_id: "dashboardgraphgeometry"
kind: system
layer: host
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Graph geometry and frame visibility

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Materializes SVG node frames, positions communities and processes viewport visibility in frame chunks.

## Historical source state

DOM nodes, minimap, transforms and virtualized classes.

## Limits and unknowns

DOM is allocated eagerly; selected node forced visible and crossing edges can be hidden when both endpoints are offscreen.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S362]] — same-file-bytes

## Directed relationships

- [[Systems/dashboardgraphack]] — reports after visibility chunks (`E1512`)
- [[Systems/dashboardcssrules]] — applies numeric viewport transform rules (`E1514`)
