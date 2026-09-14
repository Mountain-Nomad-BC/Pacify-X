---
canonical_id: "certificationcommit"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Exclusive per-file evidence publication

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Rejects source links and existing collisions then copies each target with xb.

## Historical source state

Published local evidence and release transaction journal.

## Limits and unknowns

Partial failure can leave files despite copied_file_count zero; no tree rollback or recovery owner here.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2850]] — changed-file
- [[Evidence/S2861]] — changed-file

## Directed relationships

- [[Systems/certificationverify]] — verifies after evidence commit and lock release (`E851`)
