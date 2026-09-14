---
canonical_id: "memorybroker"
kind: system
layer: memory
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Plan-bound supplied memory materialization

[[Layers/memory]] · [[Views/Full_Architecture]]

## Purpose

Builds hashed plans and checks explicitly bound supplied records, then returns all items or a quarantined empty context receipt.

## Historical source state

Plan identity, item/byte/estimated-token counts and context receipt digest.

## Limits and unknowns

Does not fetch canonical vault or authenticate lifecycle/source receipts. Freshness comparisons require supplied current revisions, which materialization omits. This is returned data, not prompt injection or durable context storage.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2349]] — same-file-bytes
- [[Evidence/S4254]] — same-file-bytes

## Directed relationships

- [[Systems/agentcallback]] — returns eligibility and receipt hash for execution binding (`E424`)
