---
canonical_id: "fixturecopyboundary"
kind: system
layer: scope
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Canonical repository fixture-copy boundary

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Prunes configured generated names, lock-suffixed entries and externally owned environment paths before copy traversal.

## Historical source state

Copytree ignore callback with repository-relative custody classification.

## Limits and unknowns

Copies selected current receipts as fixtures; copied metadata is not evidence of execution in the clone.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S4070]] — same-file-bytes
- [[Evidence/S4362]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
