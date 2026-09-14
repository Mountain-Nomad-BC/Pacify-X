---
canonical_id: "corpusjsonio"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Corpus JSONL serialization and fingerprints

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Reads JSONL, serializes canonical rows and computes lexical similarity helpers.

## Historical source state

Row stream, digest and Hamming distance.

## Limits and unknowns

Not schema validation or atomic publication.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3810]] — same-file-bytes
- [[Evidence/S3812]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
