---
canonical_id: "testgroupindex"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Test group import index and stored input closure

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Assigns top-level tests to first matching group and follows selected absolute imports.

## Historical source state

Stored file/import records and current fingerprints.

## Limits and unknowns

Relative/dynamic imports/test helpers omitted unless declared; stored imports reused by hash.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3199]] — changed-file
- [[Evidence/S3212]] — changed-file

## Directed relationships

- [[Systems/testreceiptstatus]] — supplies current group fingerprint (`E858`)
