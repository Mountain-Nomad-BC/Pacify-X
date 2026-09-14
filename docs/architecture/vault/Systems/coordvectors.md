---
canonical_id: "coordvectors"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Shared seven-rule conformance vectors

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Compares reduced Python and JavaScript reports in stable rule order.

## Historical source state

Cross-runtime fixture output comparison.

## Limits and unknowns

Does not exercise all full state/transition/startup behavior.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S4404]] — same-file-bytes
- [[Evidence/S785]] — same-file-bytes

## Directed relationships

- [[Systems/pycoordstate]] — tests reduced shared conformance subset (`E624`)
- [[Systems/coordinvariants]] — compares Node subset through runner (`E625`)
