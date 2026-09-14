---
canonical_id: "refinerynovelty"
kind: system
layer: acquisition
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Refinery weighted novelty and merge plan

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Ranks metadata similarity and chooses duplicate/enrich/variant/conflict/supersede/novel/review.

## Historical source state

One action per candidate and self-hashed merge plan.

## Limits and unknowns

Same-ID duplicate can precede supersession; canonical metadata and target fingerprints are caller supplied.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2316]] — same-file-bytes
- [[Evidence/S2318]] — same-file-bytes

## Directed relationships

- [[Systems/refinerystaging]] — supplies self-hashed proposal plan (`E680`)
- [[Systems/refineryproof]] — supplies candidate decision action counts (`E682`)
