---
canonical_id: "studiocrashworker"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Installed Studio projection crash worker

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Forces exit 91 at first skill-index atomic write in promotion/rollback, then supports a separate recovery invocation.

## Historical source state

Recovery metadata, signed receipt fields and canonical tree hash.

## Limits and unknowns

One crash boundary is covered; recovery output labels expected version without comparing actual canonical version here.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1421]] — same-file-bytes

## Directed relationships

- [[Systems/skillprojectionafter]] — interrupts first skill-index projection (`E1484`)
