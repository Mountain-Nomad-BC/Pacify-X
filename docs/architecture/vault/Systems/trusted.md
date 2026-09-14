---
canonical_id: "trusted"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Trusted evidence resolution

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Resolves evidence against scope, signed records, approved producers, freshness and integrity.

## Historical source state

ResolvedEvidence with signature, scope, freshness and integrity decisions.

## Limits and unknowns

Caller-supplied labels are weaker than resolved signed evidence.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3261]] — changed-file

## Directed relationships

- [[Systems/transfer]] — resolves transfer evidence (`E020`)
- [[Systems/verify]] — resolves signed postconditions and policy (`E096`)
- [[Systems/admission]] — resolves signed admission evidence (`E097`)
