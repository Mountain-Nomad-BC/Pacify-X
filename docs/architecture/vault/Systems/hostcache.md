---
canonical_id: "hostcache"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# Host dependency revisions and metadata cache

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Propagates domain invalidation, fingerprints selected revision counters and serves bounded in-memory or host-store metadata with requested fingerprint and age checks.

## Historical source state

Domain counters, snapshot metadata, stale flags and cache metrics.

## Limits and unknowns

Stored dependency_fingerprints are not independently compared by MetadataCache.get; invalidation and source-key construction remain caller responsibilities.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1209]] — changed-file
- [[Evidence/S1177]] — same-file-bytes
- [[Evidence/S1187]] — same-file-bytes
- [[Evidence/S1256]] — same-file-bytes

## Directed relationships

- [[Systems/bridge]] — returns eligible persisted metadata (`E285`)
