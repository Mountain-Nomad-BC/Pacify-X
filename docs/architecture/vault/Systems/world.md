---
canonical_id: "world"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Bounded operating-state projection

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Summarizes project, ledger, catalog, model, staleness, authority, hardware and release metadata for bounded startup hydration.

## Historical source state

At most 64 KiB startup projection with source revision, counts and hydration pointers.

## Limits and unknowns

Reads projections[].stale from the staleness document. The Studio promotion writer uses stale_blocked instead; that shape alone does not mark world-state projections stale.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3346]] — changed-file
- [[Evidence/S3347]] — changed-file

## Directed relationships

- [[Systems/health]] — offers a compact operational summary (`E163`)
