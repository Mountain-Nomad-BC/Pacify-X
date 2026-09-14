---
canonical_id: "evidencecache"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Revision-keyed evidence cache

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Builds keys from namespace and declared revisions, publishes content-addressed JSON blobs and an entry manifest under a file lock, and checks blob size/hash on retrieval.

## Historical source state

Content hash, revision key, manifest and canonical=False result.

## Limits and unknowns

Cache entries are derived and the caller must supply the complete correct revision set. No production caller was located in the searched runtime, extension, builders or scripts.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2079]] — same-file-bytes
- [[Evidence/S2080]] — same-file-bytes
- [[Evidence/S2078]] — same-file-bytes

## Directed relationships

- [[Systems/oslock]] — locks blob and manifest access (`E282`)
- [[Systems/cachekeypublication]] — provides optional derived value cache (`E773`)
