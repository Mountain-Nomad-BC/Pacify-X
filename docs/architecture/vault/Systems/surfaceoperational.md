---
canonical_id: "surfaceoperational"
kind: system
layer: host
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Workflow Studio lifecycle and plugin presentation

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Renders six operational views with draft/run controls and freshness-bound plugin rows.

## Historical source state

HTML/SVG renderer, no backend effect.

## Limits and unknowns

Rows require matching supplied inventory identity; actions still route through controller and host.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S310]] — same-file-bytes

## Directed relationships

- [[Systems/dashboardcontroller]] — returns action attributes for controller handling (`E994`)
