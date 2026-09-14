---
canonical_id: "sourcefaterules"
kind: system
layer: acquisition
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Incoming source disposition rules

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Selects fate/owner from source alias, package path, suffix and overlay target comparison.

## Historical source state

Planned admit/merge/retain/defer/fragment/reject classification.

## Limits and unknowns

Rationale text describes intended consolidation without checking semantic completion.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2258]] — same-file-bytes

## Directed relationships

- [[Systems/sourcefateinventory]] — classifies every enumerated source file (`E1135`)
- [[Systems/external]] — names external provider as planned canonical owner (`E1137`)
- [[Systems/security]] — names security provider as planned canonical owner (`E1138`)
