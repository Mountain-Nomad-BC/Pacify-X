---
canonical_id: "frameworkrebind"
kind: system
layer: release
currentness: changed-file
runtime_observed: false
certified: false
---
# Framework receipt identity rebinding

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Updates release metadata on an intact receipt, preserving managed content and prior receipt.

## Historical source state

Rebound event/current receipt.

## Limits and unknowns

Ignores unrelated project-check errors; matching release metadata is not independent certification trust.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1928]] — changed-file

## Directed relationships

- [[Systems/projectintegrity]] — selects receipt-specific blockers (`E600`)
- [[Systems/commissionreceipt]] — appends rebound event and replaces receipt (`E601`)
