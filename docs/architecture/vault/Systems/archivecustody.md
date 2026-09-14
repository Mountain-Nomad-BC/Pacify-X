---
canonical_id: "archivecustody"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# WAL and project-map ZIP archive paths

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Builds selected file inventory, writes deterministic ZIP and verifies every member before directly deleting selected history folders and writing receipt.

## Historical source state

ZIP manifest/content hashes, retained lexical suffix and post-deletion cleanup receipt.

## Limits and unknowns

Separate from ResourceManager. No producer lock or immediate source-tree equality check before delete. keep_latest follows names; recovery text requires manual extraction.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3358]] — changed-file
- [[Evidence/S3361]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
