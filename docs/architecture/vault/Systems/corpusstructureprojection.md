---
canonical_id: "corpusstructureprojection"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Corpus text structure projection

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Copies metadata for all records declared text.

## Historical source state

Sorted structure rows.

## Limits and unknowns

Does not extract or verify source text again.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3681]] — same-file-bytes

## Directed relationships

- [[Systems/corpusjsonio]] — reads and writes canonical JSONL rows (`E1296`)
- [[Systems/historicalskillidentity]] — supplies retained frontmatter by ID (`E1330`)
