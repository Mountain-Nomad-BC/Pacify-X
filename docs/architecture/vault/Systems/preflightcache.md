---
canonical_id: "preflightcache"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Preflight dependency-selected cache

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Reuses valid check records matching selected binding fields.

## Historical source state

Cached expensive checks and zero-time cache-hit timings.

## Limits and unknowns

No payload authentication; installed evidence identity/deep mode/transitive primitive revisions not fully bound.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2931]] — changed-file
- [[Evidence/S2947]] — changed-file

## Directed relationships

- [[Systems/preflightworkspace]] — runs uncached expensive checks (`E831`)
