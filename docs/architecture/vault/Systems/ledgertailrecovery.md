---
canonical_id: "ledgertailrecovery"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Ledger torn-tail recovery and replay

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Retains exact unterminated suffix before truncating malformed bytes or completing delimiter.

## Historical source state

Recovery receipt and valid retained stream.

## Limits and unknowns

Semantic-invalid complete suffix fails closed. This audit does not invoke recovery.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2522]] — changed-file
- [[Evidence/S2537]] — changed-file

## Directed relationships

- [[Systems/ledgerstatereducer]] — validates prefix and possible complete suffix (`E1247`)
