---
canonical_id: "corpusnearduplicates"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Corpus normalized and SimHash clustering

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Groups normalized digests then greedy neighbors within fixed prefix buckets.

## Historical source state

Review clusters and heuristic confidence.

## Limits and unknowns

Prefix buckets miss near matches; groups are not pairwise or transitive guarantees.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3671]] — same-file-bytes

## Directed relationships

- [[Systems/corpusjsonio]] — reads fingerprints and compares Hamming distance (`E1298`)
