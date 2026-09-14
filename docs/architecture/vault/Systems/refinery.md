---
canonical_id: "refinery"
kind: system
layer: acquisition
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Knowledge novelty and merge planning

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Compares candidates, classifies duplication/conflict/novelty and stages reversible merge proposals.

## Historical source state

Novelty decisions, target fingerprints and staged merge plan.

## Limits and unknowns

Merge plans explicitly perform no canonical writes.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2316]] — same-file-bytes
- [[Evidence/S2318]] — same-file-bytes
- [[Evidence/S2320]] — same-file-bytes

## Directed relationships

- [[Systems/knowledge]] — stages a proposal for canonical review (`E062`)
