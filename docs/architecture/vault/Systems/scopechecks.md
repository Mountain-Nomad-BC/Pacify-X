---
canonical_id: "scopechecks"
kind: system
layer: scope
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Context lease and switch descriptor checks

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Checks IDs, namespace metadata, same-session foreign write leases and caller teardown flags.

## Historical source state

Hashed allow/deny decision.

## Limits and unknowns

Does not reserve leases, load context or perform teardown/rebinding.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2677]] — same-file-bytes
- [[Evidence/S2678]] — same-file-bytes
- [[Evidence/S2680]] — same-file-bytes

## Directed relationships

- [[Systems/transferbinding]] — separates metadata checks from signed transfer authorization (`E565`)
