---
canonical_id: "catalogproof"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Authenticated Studio catalog status projection

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Verifies revision identity, signed validation/admission receipts, canonical skill tree, committed lifecycle transaction and current projection hashes before projecting lifecycle status.

## Historical source state

Authenticated status, reasons, current lifecycle/rollback fields, visited revisions and truncation flag.

## Limits and unknowns

A prior promotion receipt does not guarantee current promoted status. Projection drift can remove that status while preserving authenticated admission; UI fallback remains candidate when authentication is unavailable.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3127]] — same-file-bytes
- [[Evidence/S3126]] — same-file-bytes
- [[Evidence/S1278]] — same-file-bytes
- [[Evidence/S1282]] — same-file-bytes
- [[Evidence/S3121]] — same-file-bytes

## Directed relationships

- [[Systems/studioauth]] — verifies signed receipts and transaction manifests (`E275`)
- [[Systems/ui]] — supplies authenticated lifecycle status or candidate fallback (`E276`)
- [[Systems/catalogmerge]] — supplies path-keyed status without record digest in returned row (`E387`)
