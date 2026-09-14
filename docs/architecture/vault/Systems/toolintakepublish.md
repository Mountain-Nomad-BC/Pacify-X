---
canonical_id: "toolintakepublish"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Intake record and project-state publication

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Backs up previous records, replaces intake then updates and replaces state.

## Historical source state

Intake evidence reference and incremented checkpoint revision.

## Limits and unknowns

No shared lock/transaction; intake can commit before malformed-state or later write failure.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3228]] — same-file-bytes

## Directed relationships

- [[Systems/toolmanifestinventory]] — scans before apply and commissioned-state check (`E804`)
- [[Systems/lifecycleflagprojection]] — adds intake reference read by stage projection (`E806`)
