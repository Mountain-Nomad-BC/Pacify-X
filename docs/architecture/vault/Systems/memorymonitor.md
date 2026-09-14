---
canonical_id: "memorymonitor"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Workspace-wide memory health projection

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Traverses every registered project, validates records/lifecycle, reconciles index generations, reads write-queue health and runs registered integration smoke checks.

## Historical source state

Per-project counts, bytes, lifecycle/index/queue status and integration result.

## Limits and unknowns

Eligible count is certified/trusted lifecycle count, not actor/query eligibility. Healthy condition checks orphan generations and queue validity but not index activation_error. Full corpus traversal has no global bound.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3311]] — changed-file

## Directed relationships

- [[Systems/vault]] — reads complete record and lifecycle chains (`E407`)
- [[Systems/memoryactivation]] — reads reconciliation status (`E408`)
- [[Systems/memorywritequeue]] — reads latest receipt health and pending count (`E409`)
- [[Systems/integrations]] — imports targets and invokes active healthchecks (`E410`)
