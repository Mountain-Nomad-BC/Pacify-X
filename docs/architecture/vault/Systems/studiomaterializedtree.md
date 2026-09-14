---
canonical_id: "studiomaterializedtree"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Studio editor input tree and lifecycle custody

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Registers project input resource, writes or verifies deterministic target, records published/reused or retained failure.

## Historical source state

Physical tree plus materialization/lifecycle receipts.

## Limits and unknowns

Direct final-directory writes are not atomic publication; concurrent consumers have no shared lease/refcount.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1316]] — same-file-bytes

## Directed relationships

- [[Systems/studioeditorinput]] — normalizes and hashes text tree before writes (`E1029`)
