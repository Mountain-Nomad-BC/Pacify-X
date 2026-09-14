---
canonical_id: "memorypolicy"
kind: system
layer: memory
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Typed memory admission and locality policy

[[Layers/memory]] · [[Views/Full_Architecture]]

## Purpose

Checks record validity, project/actor identity and proposal certainty; proposes correction invalidations and filters retrieval candidates before semantic/locality ranking.

## Historical source state

Candidate/quarantine decision, correction rebuild categories, eligible IDs and SimHash locality.

## Limits and unknowns

Pure policy decisions differ from persisted Vault lifecycle transitions. Exact semantic matches can precede locality and lifecycle/ACL filtering remains essential.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2356]] — same-file-bytes
- [[Evidence/S2358]] — same-file-bytes
- [[Evidence/S2357]] — same-file-bytes

## Directed relationships

- [[Systems/vault]] — defines admission and retrieval eligibility (`E204`)
- [[Systems/invalidation]] — enumerates correction rebuild categories (`E205`)
