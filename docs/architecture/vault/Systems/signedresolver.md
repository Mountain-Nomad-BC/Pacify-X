---
canonical_id: "signedresolver"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Signed evidence resolution dimensions

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Resolves contained local records and optional artifacts, verifies SSH signature and compares caller scope, producer and age requirements.

## Historical source state

Independent integrity, signature, scope, producer and freshness booleans.

## Limits and unknowns

Future timestamps pass upper-age check. Optional artifacts and nonempty expected scope fields define actual binding; evidence reference filename is not compared with record evidence_id.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3262]] — changed-file

## Directed relationships

- [[Systems/sshproof]] — runs detached SSH verification (`E472`)
- [[Systems/transferbinding]] — resolves producer type freshness and project IDs (`E566`)
