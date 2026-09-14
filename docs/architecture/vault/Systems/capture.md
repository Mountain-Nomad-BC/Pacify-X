---
canonical_id: "capture"
kind: system
layer: memory
currentness: changed-file
runtime_observed: false
certified: false
---
# Memory capture and correction

[[Layers/memory]] · [[Views/Full_Architecture]]

## Purpose

Sanitizes observed events, proposes semantic memories and records explicit corrections and lifecycle changes.

## Historical source state

Source capture, proposed records, correction/supersession and invalidation receipts.

## Limits and unknowns

Capturing an observation does not certify it as reusable knowledge.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2370]] — changed-file
- [[Evidence/S3332]] — changed-file

## Directed relationships

- [[Systems/vault]] — appends scoped memory records (`E050`)
- [[Systems/invalidation]] — declares required derived rebuilds (`E057`)
- [[Systems/vaultpublish]] — caller appends explicitly constructed candidate (`E414`)
