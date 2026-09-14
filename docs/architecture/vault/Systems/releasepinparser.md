---
canonical_id: "releasepinparser"
kind: system
layer: governance
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Exact release dependency lock parser

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Parses exact pins and SHA-256 allowlists with continuation rules.

## Historical source state

Records, errors and nonempty valid flag.

## Limits and unknowns

Syntax validation does not authenticate package identity or full version semantics.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2916]] — same-file-bytes

## Directed relationships

- [[Systems/releasewheelhashes]] — supplies package hash allowlists (`E1101`)
- [[Systems/releaseenvidentity]] — supplies expected installed versions (`E1102`)
