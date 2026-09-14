---
canonical_id: "externalstagereceipt"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# External candidate receipt publication

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Writes candidate binding receipt from supplied plan and evidence strings.

## Historical source state

Candidate receipt with timestamp-tolerant idempotence.

## Limits and unknowns

No installation; direct apply does not recompute plan or source hashes.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2158]] — changed-file

## Directed relationships

- [[Systems/externalrevoke]] — provides receipt path for revocation marker (`E1109`)
