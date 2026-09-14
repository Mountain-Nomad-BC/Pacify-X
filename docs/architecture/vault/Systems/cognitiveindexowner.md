---
canonical_id: "cognitiveindexowner"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Cognitive registry merge and dependency resolution

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Merges skill, nested, agent, capability, formula, workflow and knowledge declarations into a hashed index.

## Historical source state

Records, typed edges, reviewed/unique dependency resolution and revision.

## Limits and unknowns

Reads full source JSON/body text; duplicate record merge keeps first scalar values and some dependency fields never become edges.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1894]] — changed-file

## Directed relationships

- [[Systems/cognitivenavigation]] — supplies merged records and declared edges (`E708`)
