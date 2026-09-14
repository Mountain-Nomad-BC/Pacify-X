---
canonical_id: "extensioncontextcache"
kind: system
layer: memory
currentness: changed-file
runtime_observed: false
certified: false
---
# Host context cache and workspace state

[[Layers/memory]] · [[Views/Full_Architecture]]

## Purpose

Caches coordination/provider/context for five minutes and keeps eight dashboard view states.

## Historical source state

Context envelope and in-memory view-state projections.

## Limits and unknowns

Host context key is not root-specific; state keys lowercase paths on every OS; stale context can be reused until invalidation.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1075]] — changed-file
- [[Evidence/S1079]] — changed-file
- [[Evidence/S1104]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
