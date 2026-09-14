---
canonical_id: "mapquerycache"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Project-map cache and caller validation

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Scores cached index, applies filters, expands declared relations and produces source-range hydration instructions.

## Historical source state

Top hits, reasons, merged ranges and independently read manifest revision.

## Limits and unknowns

No built-in index hash/freshness validation; path/mtime/size cache, full reads and uncapped relation frontier.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2670]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
