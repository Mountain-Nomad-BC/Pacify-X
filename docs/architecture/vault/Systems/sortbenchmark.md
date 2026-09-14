---
canonical_id: "sortbenchmark"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Sort pilot and correctness benchmark

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Checks output ordinal sequence and stability while timing candidate calls.

## Historical source state

Correct/stable flags and median/p95 timing.

## Limits and unknowns

Payload/key preservation is not checked; direct zero-repeat calls return correctness without execution.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S114]] — changed-file

## Directed relationships

- [[Systems/sortalgorithms]] — invokes selected algorithm on shallow list copy (`E1352`)
