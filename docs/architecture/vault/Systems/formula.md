---
canonical_id: "formula"
kind: system
layer: reasoning
currentness: changed-file
runtime_observed: false
certified: false
---
# Formula, dimension and uncertainty engine

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Validates formula definitions and dimensions, evaluates bounded expressions and compares candidate formulas.

## Historical source state

Formula registry, variable dimensions, numerical results and uncertainty analysis.

## Limits and unknowns

Safe evaluation and dimensional consistency do not establish physical applicability of a formula.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1890]] — changed-file
- [[Evidence/S1889]] — changed-file
- [[Evidence/S2029]] — same-file-bytes

## Directed relationships

- [[Systems/formulaadmission]] — constructs engine from caller definitions (`E693`)
