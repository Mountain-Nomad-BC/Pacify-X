---
canonical_id: "surfacecore"
kind: system
layer: host
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Dashboard and project map presentation

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Renders health/identity and sealed static project map records.

## Historical source state

HTML/SVG renderer, no backend effect.

## Limits and unknowns

Counts and map links describe supplied evidence; rendering does not execute projects.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S308]] — same-file-bytes

## Directed relationships

- [[Systems/dashboardcontroller]] — returns action attributes for controller handling (`E990`)
