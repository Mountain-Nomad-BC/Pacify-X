---
canonical_id: "studioreadconstruction"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Read-labelled Studio controller construction

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Uses open_existing for run reads but ordinary constructors for agent preview/workflow dry-run.

## Historical source state

Read result and possible authority initialization.

## Limits and unknowns

No task launch in preview/dry-run, but construction can write state.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3107]] — changed-file
- [[Evidence/S1597]] — same-file-bytes
- [[Evidence/S3289]] — changed-file

## Directed relationships

- [[Systems/studioauthority]] — may initialize through controller constructor (`E874`)
