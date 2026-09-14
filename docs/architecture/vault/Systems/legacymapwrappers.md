---
canonical_id: "legacymapwrappers"
kind: system
layer: host
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Legacy project map command wrappers

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Expose build limits, optional freshness validation and map queries.

## Historical source state

Runtime result JSON and wrapper exit status.

## Limits and unknowns

Freshness opt-in; runtime owner enforces actual behavior.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S185]] — same-file-bytes
- [[Evidence/S187]] — same-file-bytes
- [[Evidence/S213]] — same-file-bytes

## Directed relationships

- [[Systems/mapcorpus]] — forwards project traversal limits (`E1310`)
- [[Systems/mapintegrity]] — selects optional freshness check (`E1311`)
- [[Systems/mapquery]] — forwards query and top-k (`E1312`)
