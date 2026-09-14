---
canonical_id: "nativepublication"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Eligibility publication after-image recovery

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Retains before hashes/after bytes and rolls each artifact forward.

## Historical source state

Prepared/applying/committed transaction and updated files.

## Limits and unknowns

No reader atomicity, lock/fsync, before-image rollback or complete recovery path containment.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3738]] — same-file-bytes
- [[Evidence/S3741]] — same-file-bytes

## Directed relationships

- [[Systems/nativeindexidentity]] — publishes rebuilt eligibility index (`E888`)
- [[Systems/nativepackaging]] — includes packaging after-image in transaction (`E889`)
