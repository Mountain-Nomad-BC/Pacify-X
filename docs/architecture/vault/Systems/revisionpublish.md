---
canonical_id: "revisionpublish"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Immutable Studio directory publication

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Publishes a prepared revision without replacing an occupied directory, using the platform no-replace primitive and failing closed when unsupported.

## Historical source state

Prepared directory, exact immutable target and publication-collision disposition.

## Limits and unknowns

Atomic publication of one directory is distinct from a multi-file lifecycle transaction, a signed receipt and successful UI delivery.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3130]] — same-file-bytes
- [[Evidence/S3030]] — same-file-bytes
- [[Evidence/S3288]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
