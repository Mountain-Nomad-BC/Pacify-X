---
canonical_id: "studiorecord"
kind: system
layer: governance
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Studio model and single-record publication

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Normalizes model contracts, checks workflow DAG shape, writes canonical envelopes and serializes generic immutable record publication.

## Historical source state

Typed records, lifecycle flags and record replay identity.

## Limits and unknowns

Model evidence is metadata. Generic writer compares record only and does not cross-check path identity/kind/version against model fields; stronger full-tree publication belongs to callers.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3141]] — same-file-bytes
- [[Evidence/S3132]] — same-file-bytes
- [[Evidence/S3134]] — same-file-bytes
- [[Evidence/S3133]] — same-file-bytes

## Directed relationships

- [[Systems/filelease]] — locks generic record publication (`E462`)
- [[Systems/studiophys]] — reads existing record under descriptor byte cap (`E463`)
