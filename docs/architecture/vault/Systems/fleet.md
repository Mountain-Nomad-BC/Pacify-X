---
canonical_id: "fleet"
kind: system
layer: scope
currentness: changed-file
runtime_observed: false
certified: false
---
# Fleet session coordination

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Registers agent sessions, publishes canonical state transitions and reconstructs session state from event evidence.

## Historical source state

Session registry, heartbeat/transition/restart records and canonical event revision.

## Limits and unknowns

Session coordination and specialist selection do not confer the right to execute arbitrary tools.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1534]] — changed-file
- [[Evidence/S1530]] — changed-file

## Directed relationships

- [[Systems/telemetry]] — publishes canonical session transitions (`E118`)
- [[Systems/coordination]] — exposes scoped session readiness (`E119`)
