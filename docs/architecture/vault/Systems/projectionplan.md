---
canonical_id: "projectionplan"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Projection drift and rebuild planning

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Compares recorded dependency/output revisions with current bytes, propagates stale outputs through registered dependencies and separates synchronous from blocked rebuild obligations.

## Historical source state

Stale output records, revision reasons, rebuild classes and known-builder reconciliation checks.

## Limits and unknowns

plan_projection_rebuild returns a plan and does not execute builders. Known projection reconciliation checks actual builder output; declaring consumer_policy does not prove all consumers enforce it.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2701]] — changed-file
- [[Evidence/S2702]] — changed-file
- [[Evidence/S2698]] — changed-file

## Directed relationships

- [[Systems/invalidation]] — uses a separate revision propagation model (`E254`)
