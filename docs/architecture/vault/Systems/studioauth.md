---
canonical_id: "studioauth"
kind: system
layer: governance
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Studio authority and version identity

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Authenticates host approvals and receipts and allocates/revalidates immutable Studio revisions.

## Historical source state

Signed receipts, approval identity, revision allocation and lifecycle dimensions.

## Limits and unknowns

Saving a draft, admitting it and executing it are separate transitions.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3117]] — same-file-bytes
- [[Evidence/S3138]] — same-file-bytes

## Directed relationships

- [[Systems/agent]] — authenticates revisions and approvals (`E034`)
- [[Systems/workflow]] — authenticates admission and node approvals (`E035`)
- [[Systems/skillstudio]] — authenticates skill lifecycle receipts (`E036`)
- [[Systems/knowledge]] — signs and verifies canonical receipts (`E115`)
