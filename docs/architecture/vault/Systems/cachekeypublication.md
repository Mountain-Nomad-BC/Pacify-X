---
canonical_id: "cachekeypublication"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Evidence cache key blob and manifest

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Hashes declared revisions, stores content-addressed JSON blobs and updates key-to-blob mapping under lock.

## Historical source state

Noncanonical cached value, bytes/hash receipt and manifest.

## Limits and unknowns

Dependency keys can overwrite reserved revision fields; same key can be rebound to different content.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2077]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
