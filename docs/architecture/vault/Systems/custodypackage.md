---
canonical_id: "custodypackage"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Installed-proof custody packaging and signing

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Cross-checks installed proof/certificate metadata, includes required subjects and signs generated custody receipt.

## Historical source state

Signed custody JSON/signature/chunks.

## Limits and unknowns

Inner certificate signature file must exist but is not authenticated here; downstream publication wrapper checks it. Installed proof validator remains separate.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3808]] — same-file-bytes

## Directed relationships

- [[Systems/custodychunks]] — builds chunks and checks byte identity (`E490`)
- [[Systems/sshproof]] — signs generated custody receipt (`E491`)
