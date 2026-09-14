---
canonical_id: "corpuspartitionmerge"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Corpus partition stream merge

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Heap-merges declared sorted records and rejects duplicate IDs.

## Historical source state

Merged JSONL and digest/counts.

## Limits and unknowns

Input sorting assumed; output may be partial on failure.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3725]] — same-file-bytes

## Directed relationships

- [[Systems/corpusjsonio]] — serializes merged rows (`E1301`)
