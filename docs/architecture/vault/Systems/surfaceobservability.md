---
canonical_id: "surfaceobservability"
kind: system
layer: host
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Memory and activity presentation

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Separates canonical retrieval from portable context and current activity from stale/history.

## Historical source state

HTML/SVG renderer, no backend effect.

## Limits and unknowns

Readiness and liveness are supplied; displaying a record is not performing retrieval or reconciliation.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S312]] — same-file-bytes

## Directed relationships

- [[Systems/dashboardcontroller]] — returns action attributes for controller handling (`E998`)
