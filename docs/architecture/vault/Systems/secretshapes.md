---
canonical_id: "secretshapes"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Canonical credential-shape scanner

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Scans a filtered tree, redacts reported values and matches retained finding reviews to path, kind and source-line hash.

## Historical source state

Finding IDs, redacted locations, review classifications, errors and valid flag.

## Limits and unknowns

No explicit file-count or byte ceiling is applied in this scanner. Directory pruning does not apply file-specific mutable exclusions to individual files. A matching review classification other than unreviewed suppresses that finding from the blocking count; reviewer identity is retained metadata.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3005]] — changed-file
- [[Evidence/S2957]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
