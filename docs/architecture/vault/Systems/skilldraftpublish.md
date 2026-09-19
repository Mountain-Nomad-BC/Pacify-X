---
canonical_id: "skilldraftpublish"
kind: system
layer: acquisition
currentness: changed-file
runtime_observed: false
certified: false
---
# Immutable skill draft publication and closure

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Revalidates source token/tree and optional allocation, publishes exact prepared revision without replacement.

## Historical source state

Immutable revision record or exact replay; cleanup warnings after committed publication.

## Limits and unknowns

Staging and lifecycle locks differ; post-publication closure failure is reported without undoing created truth.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3043]] — changed-file
- [[Evidence/S3037]] — changed-file

## Directed relationships

- [[Systems/skilltreeidentity]] — rehashes admitted source and exact replay tree (`E637`)
- [[Systems/resourcereclaim]] — reconciles staging workspace after publication (`E638`)
