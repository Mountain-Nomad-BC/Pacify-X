---
canonical_id: "exportreplay"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Archive write and extracted replay

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Writes deterministic ZIP metadata and preflights self-produced extracted archive when required.

## Historical source state

Replay records and preflight.

## Limits and unknowns

Uncertified mode has skipped-valid preflights; no external independent acceptance.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3634]] — changed-file
- [[Evidence/S3640]] — changed-file

## Directed relationships

- [[Systems/exportpublish]] — publishes after successful required replay (`E1180`)
- [[Systems/sourcearchiveprocess]] — shares export audit concern with distinct Git revision path (`E1184`)
