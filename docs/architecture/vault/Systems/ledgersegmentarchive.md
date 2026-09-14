---
canonical_id: "ledgersegmentarchive"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Ledger segmentation and legacy equivalence

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Publishes immutable content-addressed segments and verifies exact event equality to retained JSONL.

## Historical source state

Historical segment manifest; legacy remains authoritative.

## Limits and unknowns

Not a hot-path replacement; later appends make prior manifest stale.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2551]] — changed-file

## Directed relationships

- [[Systems/ledgerstatereducer]] — verifies segment event equality and chain semantics (`E1249`)
