---
canonical_id: "corpusrehash"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Corpus map digest refresh

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Rehashes inventory maps and updates adjacent summary hashes.

## Historical source state

Map-level digest projection.

## Limits and unknowns

Does not revalidate source bytes, counts or sanitization.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3731]] — same-file-bytes

## Directed relationships

- [[Systems/corpuspartitionreport]] — refreshes summary map digests (`E1309`)
