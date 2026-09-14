---
canonical_id: "hygienequarantine"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Pre-candidate quarantine journal

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Snapshots, journals and moves selected trees into root quarantine.

## Historical source state

Started/moved records and tree evidence.

## Limits and unknowns

One pre-move snapshot; resume may replace mismatched historical evidence.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3820]] — changed-file

## Directed relationships

- [[Systems/hygienetargets]] — selects named targets (`E925`)
- [[Systems/hygienevalidation]] — provides retained manifest and tree (`E926`)
