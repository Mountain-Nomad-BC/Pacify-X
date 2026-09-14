---
canonical_id: "contractlint"
kind: system
layer: reasoning
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Semantic effect contract linting

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Checks declared reads, writes, epistemic effects, evidence requirements and rollback against supplied observed or prohibited effects.

## Historical source state

Errors, warnings and contract validity report.

## Limits and unknowns

Observed effects must be supplied; the linter itself does not observe OS effects or authorize execution.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2424]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
