---
canonical_id: "cognitivenavigation"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Cognitive scoring and hydration plan

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Ranks index fields/aliases/fuzzy and supplied dense ranks, then emits selected and outgoing dependency paths.

## Historical source state

Hits, path-only hydration list, unresolved and truncated flags.

## Limits and unknowns

No freshness/hash/admission checks; selectable includes reference_only and every selectable record gets positive baseline score.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1907]] — same-file-bytes

## Directed relationships

- [[Systems/cognitive]] — requires explicit operation and payload translation (`E709`)
