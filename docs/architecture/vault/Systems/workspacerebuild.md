---
canonical_id: "workspacerebuild"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Workspace projection reconstruction and compensation

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Replays valid events, prepares registry/sessions and replaces projections with existing-target rollback.

## Historical source state

Prepared/committed transaction and recovered-operation events.

## Limits and unknowns

Sequential publication, incomplete extra/new-target reconciliation and later evidence outside compensation.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3336]] — changed-file

## Directed relationships

- [[Systems/workspaceevents]] — reconstructs from validated history then appends closure (`E586`)
- [[Systems/workspaceprojection]] — replaces registry seal and sessions sequentially (`E587`)
