---
canonical_id: "observerconsent"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Observer consent and command plan

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Matches caller consent scopes/configuration with backend metadata and fixed-profile builders.

## Historical source state

Explicit consent object and command vectors.

## Limits and unknowns

No signed host grant; plan digest is declared and commands mapping mutable.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2570]] — changed-file
- [[Evidence/S2569]] — changed-file
- [[Evidence/S2583]] — changed-file
- [[Evidence/S2582]] — changed-file

## Directed relationships

- [[Systems/observernative]] — checks plan and starts backend (`E962`)
