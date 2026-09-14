---
canonical_id: "knowledge"
kind: system
layer: memory
currentness: changed-file
runtime_observed: false
certified: false
---
# Canonical knowledge controller

[[Layers/memory]] · [[Views/Full_Architecture]]

## Purpose

Proposes, verifies, approves, promotes, rejects and rolls back signed knowledge revisions with source/evidence and concurrency checks.

## Historical source state

Signed proposal history, canonical content-addressed revisions and head.json.

## Limits and unknowns

This store is distinct from MemoryVault; no universal automatic bridge between the two is established.

## Historical suggested evolution

Promotion changes canonical heads; decay can revoke authoritative resolution until revalidation.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2295]] — changed-file
- [[Evidence/S2294]] — changed-file
- [[Evidence/S2298]] — changed-file

## Directed relationships

- [[Systems/dashboard]] — publishes canonical/proposal browse views (`E058`)
- [[Systems/reuse]] — binds measurements to promoted revision (`E080`)
- [[Systems/knowledgebrowse]] — projects signed heads and rollback history (`E261`)
