---
canonical_id: "schedulersimulationtests"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Observe-only scheduler policy fixtures

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Exercises declared metadata counts, dependency order, blocked gates, scoring factors and replay hash.

## Historical source state

Simulated would_dispatch events with no execution authority.

## Limits and unknowns

Direct Python tests do not exercise the broken CLI scheduling simulate loader entry path.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S4130]] — same-file-bytes

## Directed relationships

- [[Systems/schedulesimulation]] — calls direct deterministic simulator (`E1430`)
