---
canonical_id: "externalmetadata"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# External catalog ranking and metadata hydration

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Loads deferred source metadata, ranks lexical matches and returns size-limited top-level projections.

## Historical source state

Metadata candidates, never installed bodies.

## Limits and unknowns

Limits follow full input loading; metadata trust differs from runtime authority.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2167]] — changed-file

## Directed relationships

- [[Systems/externalstageplan]] — supplies bundle and candidate identities (`E1106`)
