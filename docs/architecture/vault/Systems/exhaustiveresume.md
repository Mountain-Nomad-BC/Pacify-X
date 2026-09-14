---
canonical_id: "exhaustiveresume"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Exhaustive walk predecessor reuse

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Accepts prior records and selects retries or a regex subset.

## Historical source state

Copied predecessor records and selected indexes.

## Limits and unknowns

Equal matrix digest bypasses source comparison and stage checks; error-free incomplete records are not retried by default.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S557]] — changed-file

## Directed relationships

- [[Systems/exhaustivepublish]] — selects and carries predecessor records (`E1548`)
