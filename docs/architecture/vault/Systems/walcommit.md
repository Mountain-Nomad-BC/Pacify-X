---
canonical_id: "walcommit"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# WAL before-image capture and sequential publication

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Recovers older pending work, captures current targets, optionally validates transitions, stages images and replaces targets through sealed manifest phases.

## Historical source state

Prepared/applying/committed manifest and archived transaction.

## Limits and unknowns

Recovery consistency is distinct from concurrent reader isolation. Before image is captured at commit time, not at the caller earlier read; owner precommit invariant is optional.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3274]] — changed-file
- [[Evidence/S3267]] — changed-file

## Directed relationships

- [[Systems/walinspect]] — recovers prior pending transactions before new admission stages (`E455`)
- [[Systems/archivecustody]] — leaves committed directories eligible for separate archive invocation (`E457`)
- [[Systems/filelease]] — serializes one journal writer and recovery (`E460`)
- [[Systems/pycoordwalguard]] — invokes optional validator when explicitly supplied (`E623`)
