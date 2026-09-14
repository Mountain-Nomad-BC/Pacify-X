---
canonical_id: "corpusassetclassify"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Corpus lexical asset classification

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Uses duplicate ordering and first path/heading rule to assign a class.

## Historical source state

Class, confidence, review state and zero-unknown count.

## Limits and unknowns

Zero unknown means fallback assigned, not semantics reviewed.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3598]] — same-file-bytes

## Directed relationships

- [[Systems/corpusjsonio]] — reads inventory and writes classified rows (`E1299`)
- [[Systems/corpusreviewclusters]] — provides class domain and review state (`E1306`)
- [[Systems/historicalassetdisposition]] — supplies classified asset rows (`E1331`)
