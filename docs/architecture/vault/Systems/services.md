---
canonical_id: "services"
kind: system
layer: acquisition
currentness: changed-file
runtime_observed: false
certified: false
---
# Service capability routing

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Routes service-family requests to catalog metadata and bounded skills for integrations such as n8n and Supabase.

## Historical source state

Service catalog candidates, selected skill bodies and routing receipts.

## Limits and unknowns

A routed service skill does not establish a live remote connection, credential or successful transaction.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3024]] — changed-file
- [[Evidence/S3022]] — changed-file

## Directed relationships

- [[Systems/catalog]] — hydrates routed admitted skill bodies (`E069`)
- [[Systems/serviceblueprints]] — offers external deployment and schema scaffolds (`E326`)
- [[Systems/serviceroute]] — routes without loading bodies (`E530`)
- [[Systems/servicehydrate]] — hydrates independently supplied IDs (`E531`)
