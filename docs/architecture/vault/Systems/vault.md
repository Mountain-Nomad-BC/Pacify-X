---
canonical_id: "vault"
kind: system
layer: memory
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Canonical project memory vault

[[Layers/memory]] · [[Views/Full_Architecture]]

## Purpose

Stores individually revisioned JSON records and parallel notes, with chained lifecycle and eligible retrieval.

## Historical source state

Immutable record revisions, lifecycle events, notes, supersession and ACLs.

## Limits and unknowns

Only trusted/certified, unexpired, authorized records participate in retrieval.

## Historical suggested evolution

Verified corrections and lifecycle transitions change which records future queries can retrieve.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2401]] — same-file-bytes
- [[Evidence/S2402]] — same-file-bytes

## Directed relationships

- [[Systems/memoryindex]] — builds candidate index generation (`E052`)
- [[Systems/recall]] — provides eligible memory records (`E054`)
- [[Systems/dashboard]] — serves canonical memory views (`E093`)
- [[Systems/workspacerecall]] — supplies lifecycle-filtered records before rich caller ranking (`E417`)
