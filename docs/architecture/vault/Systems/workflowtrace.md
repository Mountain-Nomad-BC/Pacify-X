---
canonical_id: "workflowtrace"
kind: system
layer: host
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Workflow trace identity projection

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Projects node receipts for the selected workflow version/run, preserving failures, retries and recovery while clearing conflicting identities.

## Historical source state

Trace identity, node receipts, next node and replace/clear/unchanged decision.

## Limits and unknowns

The dashboard has a separate implementation from the tested CommonJS helper. Source similarity does not establish that a test of one executes the other; identity matching alone is not signature verification.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S444]] — same-file-bytes
- [[Evidence/S1366]] — same-file-bytes

## Directed relationships

- [[Systems/ui]] — replaces or clears the displayed run trace (`E289`)
- [[Systems/workflowtracehelper]] — has independently tested module projection (`E1069`)
