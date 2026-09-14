---
canonical_id: "startupconfig"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Validated startup configuration

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Loads TOML, rejects disabled fail-closed and project-root boundaries, enforces positive integer budgets and lifecycle checkpoint/unload requirements.

## Historical source state

Immutable startup, budget and lifecycle dataclasses.

## Limits and unknowns

Validation concerns this schema and these explicit checks; it does not execute or independently measure the configured policies.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1945]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
