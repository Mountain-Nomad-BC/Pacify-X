---
canonical_id: "goldencallback"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Golden callback benchmarks

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Invokes the caller runner for each prompt and compares exact or contained expected text.

## Historical source state

Per-case result, expected/actual hashes and pass rate.

## Limits and unknowns

No callback deadline or process custody; runner owns actual effects.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1861]] — changed-file

## Directed relationships

- [[Systems/cognitivepassport]] — supplies benchmark decision (`E729`)
