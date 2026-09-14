---
canonical_id: "modelselection"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Trait-ranked model inventory selection

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Filters modality/tool requirements, ranks metadata for traits/context/privacy and joins selected model ID back to inventory.

## Historical source state

Model ranking receipt and chosen attachment.

## Limits and unknowns

Availability is caller metadata. Duplicate model IDs can resolve ranking winner to a different first inventory row; warm cost and failure modes not scored.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2430]] — changed-file
- [[Evidence/S2432]] — changed-file

## Directed relationships

- [[Systems/attachmentidentity]] — constructs selected exact attachment (`E511`)
