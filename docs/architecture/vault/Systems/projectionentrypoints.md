---
canonical_id: "projectionentrypoints"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Graph effect route identity and test-index writers

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Thin wrappers publish their core builders with differing validity contracts.

## Historical source state

Generated registry files and selected counts.

## Limits and unknowns

Publication and source-index consistency do not establish behavioral proof.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3482]] — same-file-bytes
- [[Evidence/S3549]] — same-file-bytes
- [[Evidence/S3484]] — same-file-bytes
- [[Evidence/S3566]] — same-file-bytes
- [[Evidence/S3574]] — same-file-bytes

## Directed relationships

- [[Systems/effectsyntaxinventory]] — discovers syntactic effect ownership (`E1197`)
- [[Systems/graphprojection]] — writes canonical graph artifacts (`E1198`)
- [[Systems/testgroupindex]] — builds group/import index (`E1199`)
