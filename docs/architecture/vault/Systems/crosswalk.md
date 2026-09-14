---
canonical_id: "crosswalk"
kind: system
layer: acquisition
currentness: changed-file
runtime_observed: false
certified: false
---
# Mechanism novelty and ownership crosswalk

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Classifies supplied mechanisms as enrichment, novel candidate or review against known canonical owners.

## Historical source state

Mechanism IDs, source evidence, canonical-owner references and delta hash.

## Limits and unknowns

Mechanism classification does not automatically implement or promote the proposed delta.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1939]] — changed-file
- [[Evidence/S2269]] — same-file-bytes

## Directed relationships

- [[Systems/refinery]] — directs novelty toward refinery admission (`E061`)
