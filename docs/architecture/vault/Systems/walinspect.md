---
canonical_id: "walinspect"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Read-only WAL inspection and recovery choice

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Fingerprints pending journal around inspection; validates images and current targets; selects unprepared archive or published roll-forward.

## Historical source state

Required recovery actions, journal fingerprint and retained committed/rolled-back folders.

## Limits and unknowns

Double fingerprint covers pending journal, not stable external targets. Inspection bounds follow enumeration/read work. Archived generations may be superseded; ZIP archives are outside automatic recovery.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3275]] — changed-file
- [[Evidence/S3273]] — changed-file

## Directed relationships

- [[Systems/walcommit]] — rolls forward published manifest exact images (`E456`)
