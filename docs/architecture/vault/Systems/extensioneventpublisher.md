---
canonical_id: "extensioneventpublisher"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Extension canonical event queue and child

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Drains activity event batches to Python visibility publish and reports delivery/drop health.

## Historical source state

Actual extension-to-Python publication route.

## Limits and unknowns

In-memory queue acceptance does not mean canonical persistence.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S896]] — changed-file
- [[Evidence/S1098]] — changed-file

## Directed relationships

- [[Systems/cli]] — spawns visibility publish ingress (`E984`)
- [[Systems/listenerhealth]] — reports publication or drop health (`E986`)
