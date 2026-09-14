---
canonical_id: "improvement"
kind: system
layer: reasoning
currentness: changed-file
runtime_observed: false
certified: false
---
# Continuous-improvement backlog

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Compiles supplied sources and uses supplied usage/failure rates to propose skill evolution actions.

## Historical source state

Candidate skill IDs, improvement backlog and bundle identity.

## Limits and unknowns

automatic_activation is false; recommendations need a separate construction/admission path.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2686]] — same-file-bytes
- [[Evidence/S2311]] — changed-file

## Directed relationships

- [[Systems/foundry]] — compiles sources into candidates (`E085`)
- [[Systems/skillstudio]] — proposes future skill changes (`E086`)
