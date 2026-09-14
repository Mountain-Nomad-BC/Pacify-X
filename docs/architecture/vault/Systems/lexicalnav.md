---
canonical_id: "lexicalnav"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Weighted metadata navigation and working sets

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Ranks token matches by field weight and inverse document frequency, boosts exact governed aliases, reports missing inputs and constructs dependency-bounded working sets with bundle rollback.

## Historical source state

Rank reasons, lifecycle exclusions, metadata revision, selected IDs and rejected bundles.

## Limits and unknowns

Semantic navigation here is deterministic lexical metadata scoring. Missing inputs are reported, not universally rejected; the caller controls allowed statuses. There is no embedding generation in these functions.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3025]] — same-file-bytes
- [[Evidence/S3026]] — same-file-bytes
- [[Evidence/S1670]] — changed-file

## Directed relationships

- [[Systems/procedures]] — hands selected identifiers to a separate hydration owner (`E230`)
