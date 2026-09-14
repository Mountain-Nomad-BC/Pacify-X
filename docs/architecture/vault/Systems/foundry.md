---
canonical_id: "foundry"
kind: system
layer: acquisition
currentness: changed-file
runtime_observed: false
certified: false
---
# Knowledge foundry and calculation compiler

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Normalizes source text into evidence-linked objects, compiles bounded calculation specifications and emits skill/schema/benchmark candidates.

## Historical source state

Candidate bundle, source hashes, knowledge objects, calculations and schemas.

## Limits and unknowns

Text extraction is line/heading/list based and skill templates use fixed capability terms; it is not an arbitrary algorithm synthesizer.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2309]] — changed-file
- [[Evidence/S2308]] — changed-file

## Directed relationships

- [[Systems/foundrybridge]] — exports candidate lineage (`E064`)
- [[Systems/foundryextract]] — compiles supplied text into line objects and templates (`E684`)
