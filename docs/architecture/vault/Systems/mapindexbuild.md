---
canonical_id: "mapindexbuild"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Project retrieval document projection

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Builds metadata documents, postings, term weights and relation links among files and their symbols/routes/configuration/integrations.

## Historical source state

Index and bounded lexical routing-feature tokens.

## Limits and unknowns

Dependency/architecture arguments do not add their edges here. Whole-file document range can dominate hydration; duplicate service identities overwrite documents.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2654]] — same-file-bytes
- [[Evidence/S2663]] — same-file-bytes

## Directed relationships

- [[Systems/mappromotion]] — writes index alongside other map artifacts (`E549`)
- [[Systems/mapquerycache]] — supplies index and separate manifest (`E552`)
