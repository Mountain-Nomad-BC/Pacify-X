---
canonical_id: "refinerymetrics"
kind: system
layer: reasoning
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Refinery retrieval and calibration metrics

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Computes reciprocal rank and binary NDCG, then compares caller train/holdout objectives.

## Historical source state

Metric rows, forbidden-hit validity and manual calibration acceptance.

## Limits and unknowns

Duplicate returned IDs can inflate NDCG; no-result failures do not invalidate; empty disjoint inputs can accept.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2317]] — same-file-bytes
- [[Evidence/S2314]] — same-file-bytes

## Directed relationships

- [[Systems/refineryproof]] — supplies valid and accepted component fields (`E681`)
