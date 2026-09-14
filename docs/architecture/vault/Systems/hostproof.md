---
canonical_id: "hostproof"
kind: system
layer: governance
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Host operation and workflow approval consumption

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Validates exact RSA host proof and payload or local workflow approval, then reserves single-use identity with exclusive marker creation.

## Historical source state

Nonce or approval consumption marker before downstream execution.

## Limits and unknowns

Host RSA proof differs from local HMAC receipt signing. Marker reservation survives later publication or operation failure; no automatic retry authorization follows.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3120]] — same-file-bytes
- [[Evidence/S3119]] — same-file-bytes

## Directed relationships

- [[Systems/studioauthority]] — records one-use proof consumption (`E438`)
