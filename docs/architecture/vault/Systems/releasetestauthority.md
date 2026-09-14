---
canonical_id: "releasetestauthority"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Release and platform fixture authority

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Checks revoked certificate hashes, selected certificate verification, publication workflow text, supply-chain serialization and platform policy.

## Historical source state

Mixed byte-binding, policy, source-string and synthetic fixture assertions.

## Limits and unknowns

Marketplace workflow assertions are local source checks; they do not independently establish remote publication or signature verification.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S4339]] — same-file-bytes
- [[Evidence/S4340]] — same-file-bytes
- [[Evidence/S4353]] — same-file-bytes
- [[Evidence/S4360]] — changed-file
- [[Evidence/S4301]] — same-file-bytes
- [[Evidence/S4320]] — changed-file

## Directed relationships

- [[Systems/faultcampaignrunner]] — loads lane metadata without running campaign (`E1412`)
- [[Systems/releaseenvidentity]] — checks declared platform matrix (`E1413`)
