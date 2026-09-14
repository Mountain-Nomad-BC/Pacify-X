---
canonical_id: "vaultpublish"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Memory append and lifecycle publication

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Under vault lock writes lifecycle event, anchor and head, then sealed record JSON and human-readable Markdown note.

## Historical source state

Multiple immutable artifacts and replaced lifecycle head.

## Limits and unknowns

No WAL makes the entire append atomic; readers do not take writer lock. Initial valid supplied lifecycle state is accepted rather than forced candidate. Evidence strings are not authenticated by this primitive.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2385]] — same-file-bytes
- [[Evidence/S2389]] — same-file-bytes

## Directed relationships

- [[Systems/vault]] — publishes canonical record and parallel note (`E415`)
