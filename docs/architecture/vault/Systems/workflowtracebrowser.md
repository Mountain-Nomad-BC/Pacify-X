---
canonical_id: "workflowtracebrowser"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Browser workflow trace identity and receipt projection

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Selects current run, fills expected identity and projects node state for UI.

## Historical source state

Current identity, per-node trace and metadata in controller.

## Limits and unknowns

Missing hash accepted; identity fallback and absent freshness checks can preserve ambiguous trace.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S442]] — same-file-bytes

## Directed relationships

- [[Systems/dashboardcontroller]] — replaces clears or preserves local trace (`E1073`)
