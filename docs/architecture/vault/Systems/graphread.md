---
canonical_id: "graphread"
kind: system
layer: host
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Dashboard graph projection reader

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Loads bounded repository graphs or the cognitive capability index, normalizes edge spellings and returns filtered graph neighborhoods and pages.

## Historical source state

Graph nodes, edges, filters, pagination, source locator and read limitations.

## Limits and unknowns

Repository input is bounded16MiB/50k nodes/200k edges; capability index uses generic JSON fallback. Path and overview responses ignore node/edge output caps. Full mode pages nodes/edges independently. No per-read projection_staleness check or source receipt verification.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2017]] — same-file-bytes

## Directed relationships

- [[Systems/surfacegraph]] — offers loaded graph projection through controller (`E1005`)
