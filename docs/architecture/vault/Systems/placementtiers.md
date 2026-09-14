---
canonical_id: "placementtiers"
kind: system
layer: governance
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Placement scoring and promotion metadata

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Scores baseline alternatives, binds supplied workload observations and advances explicit evidence-shaped promotion gates.

## Historical source state

Recommendation and tier metadata, never automatic migration.

## Limits and unknowns

Higher promotion gates check predecessor hash shapes/flags rather than recompute/authenticate predecessor and actual evidence. Current baseline can remain selected despite failed eligibility.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2142]] — same-file-bytes
- [[Evidence/S2143]] — same-file-bytes
- [[Evidence/S2145]] — same-file-bytes

## Directed relationships

- [[Systems/placementpublish]] — can publish lifecycle artifact by explicit call (`E508`)
