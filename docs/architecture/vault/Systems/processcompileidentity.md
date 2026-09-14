---
canonical_id: "processcompileidentity"
kind: system
layer: acquisition
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Process verification flags and catalog-dependent compilation

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Validates process schema, trusts verification booleans and Jaccard-matches catalog IDs/tags.

## Historical source state

Inert candidate, linear step chain, receipt and project evidence path.

## Limits and unknowns

Process hash excludes catalog identity; same record can recompile differently and then fail existing receipt comparison.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2616]] — same-file-bytes
- [[Evidence/S2617]] — same-file-bytes

## Directed relationships

- [[Systems/skillstudio]] — requires explicit package construction and admission (`E675`)
