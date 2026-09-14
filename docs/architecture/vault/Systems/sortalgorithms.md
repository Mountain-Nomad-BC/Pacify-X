---
canonical_id: "sortalgorithms"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Sort candidate algorithms and compatibility

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Provides comparison, bucket, counting and radix candidates with integer-span gating.

## Historical source state

Candidate outputs and compatibility labels.

## Limits and unknowns

Counting/radix preserve sample order, which can differ from original ordinal order after reservoir replacement.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S107]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
