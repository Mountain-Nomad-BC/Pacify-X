---
canonical_id: "legacyincompleteids"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Incomplete signal detection and identity

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Finds lexical/AST signals with content-derived IDs.

## Historical source state

Deduplicated finding set.

## Limits and unknowns

Same-file pass sites collapse because identity lacks context.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S017]] — same-file-bytes

## Directed relationships

- [[Systems/legacyincompletereviews]] — provides deduplicated signal identities (`E1316`)
