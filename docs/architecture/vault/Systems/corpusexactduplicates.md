---
canonical_id: "corpusexactduplicates"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Corpus exact duplicate grouping

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Groups declared SHA and size, retaining sorted unique IDs.

## Historical source state

Exact groups and duplicate counts.

## Limits and unknowns

No source rehash or reviewed canonical choice.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3676]] — same-file-bytes

## Directed relationships

- [[Systems/corpusjsonio]] — reads declared hash identities (`E1297`)
- [[Systems/corpusassetclassify]] — provides implicit canonical member ordering (`E1305`)
