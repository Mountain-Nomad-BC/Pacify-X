---
canonical_id: "iwsetup"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Installed Studio setup and candidate save

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Cancels and approves setup, saves typed agent/workflow/skill candidates and reopens catalog rows.

## Historical source state

Typed setup/draft receipts and catalog matches.

## Limits and unknowns

Setup exact request matching is stronger; candidate hash shapes and row visibility are not artifact rehashing.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S744]] — changed-file
- [[Evidence/S754]] — changed-file

## Directed relationships

- [[Systems/iwlifecycle]] — supplies saved candidate observations (`E1575`)
- [[Systems/iwrevision]] — supplies predecessor candidate (`E1576`)
- [[Systems/iwnative]] — requests setup and authority UI through shared helper (`E1578`)
