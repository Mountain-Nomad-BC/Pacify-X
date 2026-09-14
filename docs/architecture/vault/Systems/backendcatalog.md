---
canonical_id: "backendcatalog"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Neutral backend capability selection

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Checks supplied backend-domain metadata and selects the least-effect eligible capability per required domain, breaking ties by cost and ID.

## Historical source state

Selected backend metadata, unresolved domains, zero hydrated bodies and no authority grant.

## Limits and unknowns

A provider-adapter string does not create a database, webhook, realtime connection or storage service.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1625]] — same-file-bytes
- [[Evidence/S1624]] — same-file-bytes

## Directed relationships

- [[Systems/integrations]] — identifies proposed service adapter metadata (`E203`)
- [[Systems/backendleastmetadata]] — exposes separate selection helper (`E801`)
