---
canonical_id: "iwfaults"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Outage and diagnostic disposition

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Partitions expected host faults and records disconnected/recovered surface alerts.

## Historical source state

Retained/recovered errors and outage stage contribution.

## Limits and unknowns

Broad text classifiers, historical marketplace assumption and early partition can omit relevant diagnostics.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S660]] — same-file-bytes
- [[Evidence/S664]] — same-file-bytes
- [[Evidence/S667]] — same-file-bytes

## Directed relationships

- [[Systems/iwpublish]] — supplies partitioned diagnostic arrays (`E1607`)
