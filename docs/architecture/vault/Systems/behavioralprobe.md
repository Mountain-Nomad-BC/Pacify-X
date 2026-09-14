---
canonical_id: "behavioralprobe"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Behavioral control callback execution

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Invokes each declared control and comparison, measures elapsed time and checks discriminating outputs.

## Historical source state

Observed values, errors, timing and probe result.

## Limits and unknowns

Latency is checked after completion; invalid suite declarations do not prevent callbacks.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1631]] — changed-file

## Directed relationships

- [[Systems/behavioraldelta]] — requires explicit case and evidence conversion (`E747`)
