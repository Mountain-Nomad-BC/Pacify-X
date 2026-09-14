---
canonical_id: "projectmap"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Repository intelligence and impact

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Builds source/symbol maps, answers bounded repository questions and traces upstream change impact.

## Historical source state

Project map manifest, nodes/edges and source revision.

## Limits and unknowns

A source map supports routing and impact; reference edges alone do not prove runtime behavior.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2663]] — same-file-bytes
- [[Evidence/S2643]] — changed-file

## Directed relationships

- [[Systems/router]] — supplies fresh repository features (`E023`)
- [[Systems/engineering]] — supplies repository evidence for analysis (`E127`)
- [[Systems/mapquery]] — publishes queryable repository metadata (`E191`)
- [[Systems/mapquerycache]] — serves promoted metadata and hydration ranges (`E533`)
- [[Systems/impacttrace]] — offers fresh-map impact analysis (`E536`)
- [[Systems/pythonworkplane]] — admits expensive explicit map builder (`E544`)
- [[Systems/mapcorpus]] — selects and inventories source (`E545`)
