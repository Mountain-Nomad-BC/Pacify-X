---
canonical_id: "sanitizerpreflight"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Sanitizer preservation selection and receipt

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Requires an empty external preservation root and copies files affected by text or path changes.

## Historical source state

Preservation copies, source hashes and recovery receipt.

## Limits and unknowns

Source hashes are taken after copy without checking destination; excluded-name nodes can still enter changed_nodes preservation.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S4019]] — same-file-bytes

## Directed relationships

- [[Systems/sanitizerrewrite]] — copies affected files before rewrite loop (`E1433`)
