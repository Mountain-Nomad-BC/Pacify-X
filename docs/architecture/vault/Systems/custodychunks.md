---
canonical_id: "custodychunks"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Custody ZIP chunking and reconstruction

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Builds deterministic archive chunks, checks ordered hashes and extracts path-validated ZIP to a new directory.

## Historical source state

Unsigned byte identity receipt and extracted tree.

## Limits and unknowns

Verification reads chunks before reconstruction rereads them without final rehash. Certificate/subject bindings reread files after archive creation. Signature authority is caller-owned.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2084]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
