---
canonical_id: "publicationfixtureauthority"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Publication and workflow fixture authority

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Tests publication identity changes and all 17 registered workflow routes with supplied evidence fixtures.

## Historical source state

Positive/negative fixture assertions and workflow completion counts.

## Limits and unknowns

Publication signatures/custody are mocked valid; workflow acceptance uses synthetic resolver and supplied true flags, not independent operational proof.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S4421]] — same-file-bytes
- [[Evidence/S4413]] — same-file-bytes

## Directed relationships

- [[Systems/tests]] — contributes fixture evidence (`E1467`)
