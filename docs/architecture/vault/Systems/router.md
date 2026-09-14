---
canonical_id: "router"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Capability discovery and routing

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Normalizes a request, discovers across sources, expands bounded relationships, ranks candidates and constructs a minimum capability package.

## Historical source state

Task envelope, ranked candidates, minimum package and route receipt.

## Limits and unknowns

route_task explicitly does not execute its selected capabilities.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1674]] — changed-file
- [[Evidence/S1702]] — same-file-bytes
- [[Evidence/S2780]] — same-file-bytes

## Directed relationships

- [[Systems/plan]] — compiles selected package and revisions (`E024`)
- [[Systems/lexicalnav]] — runs each metadata source before fusion (`E226`)
- [[Systems/routingnormalize]] — normalizes before source discovery (`E499`)
- [[Systems/modelselection]] — optionally selects model while compiling route plan (`E510`)
- [[Systems/mapquerycache]] — queries after separate fresh-map validation (`E534`)
- [[Systems/classifyheuristic]] — classifies text for capability routing (`E611`)
