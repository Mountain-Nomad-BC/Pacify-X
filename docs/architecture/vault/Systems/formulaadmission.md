---
canonical_id: "formulaadmission"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Formula definition registration and example checks

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Registers unique formula IDs; executable definitions require metadata, dimensions and passing supplied examples.

## Historical source state

In-memory formula registry.

## Limits and unknowns

Property cases and authority are strings; example checks do not enforce all runtime input-domain checks.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1890]] — changed-file

## Directed relationships

- [[Systems/formulauncertainty]] — evaluates stored definition and numerical sensitivities (`E694`)
