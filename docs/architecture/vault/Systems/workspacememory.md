---
canonical_id: "workspacememory"
kind: system
layer: memory
currentness: changed-file
runtime_observed: false
certified: false
---
# Workspace canonical memory access and orphan moves

[[Layers/memory]] · [[Views/Full_Architecture]]

## Purpose

Binds memory mutation/search to project session and supplies multi-session browser and orphan reconciliation.

## Historical source state

Candidate/certified records, browse selections and recoverable quarantine.

## Limits and unknowns

Browser trusts all active-session actors; orphan classification precedes vault lock.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3341]] — changed-file
- [[Evidence/S3330]] — changed-file
- [[Evidence/S3337]] — changed-file

## Directed relationships

- [[Systems/vaultpublish]] — delegates record lifecycle and indexing (`E589`)
