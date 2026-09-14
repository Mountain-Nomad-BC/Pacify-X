---
canonical_id: "releasecampaignsupersession"
kind: system
layer: release
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Release archives and phase rewind

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Archives eligible predecessors and clears successor campaign.

## Historical source state

Retained predecessor hash and new pointer.

## Limits and unknowns

Archive/pointer writes separate; campaign ID path trust.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2827]] — same-file-bytes
- [[Evidence/S2828]] — same-file-bytes

## Directed relationships

- [[Systems/releasecampaignidentity]] — archives then clears successor (`E904`)
