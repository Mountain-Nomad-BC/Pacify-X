---
canonical_id: "graphsourcebinding"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Graph authority and revision reconciliation

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Validates graph inventory/output digest and replaces declared source/output revision metadata.

## Historical source state

Graph manifest and reconciliation result.

## Limits and unknowns

Validation checks source revision syntax, not source freshness; reconciliation does not run graph builders.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2706]] — changed-file
- [[Evidence/S2703]] — changed-file

## Directed relationships

- [[Systems/projectionfreshness]] — shares file/tree revision primitive (`E655`)
