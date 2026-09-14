---
canonical_id: "memoryindex"
kind: system
layer: memory
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Derived memory index generations

[[Layers/memory]] · [[Views/Full_Architecture]]

## Purpose

Builds candidate generations from exact record identities, SimHash, relations and semantic projections, then validates before activation.

## Historical source state

Immutable generation entries/manifest and activation history.

## Limits and unknowns

Candidate validation checks its included historical revisions, not latest/full corpus; explicit activation is separate. Direct vault/workspace search reads canonical records, not this activated index.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2399]] — same-file-bytes
- [[Evidence/S2403]] — same-file-bytes

## Directed relationships

- [[Systems/memoryactivation]] — validates then explicitly activates candidate (`E416`)
