---
canonical_id: "releasecampaignidentity"
kind: system
layer: release
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Release campaign source identity

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Clears/applies one self-hashed source and harness identity.

## Historical source state

Cleared, active, failed or certified state.

## Limits and unknowns

Structural identity is distinct from signed certification.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2822]] — same-file-bytes
- [[Evidence/S2820]] — same-file-bytes

## Directed relationships

- [[Systems/releasecampaignclaim]] — binds source and prefix (`E900`)
