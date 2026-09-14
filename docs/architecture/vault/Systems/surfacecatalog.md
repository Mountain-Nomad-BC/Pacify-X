---
canonical_id: "surfacecatalog"
kind: system
layer: host
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Agent and capability catalog presentation

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Renders agent availability and domain-filtered skills/tools catalogs.

## Historical source state

HTML/SVG renderer, no backend effect.

## Limits and unknowns

Catalog badges and visible actions do not independently prove readiness or authority.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S309]] — same-file-bytes

## Directed relationships

- [[Systems/dashboardcontroller]] — returns action attributes for controller handling (`E992`)
