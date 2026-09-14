---
canonical_id: "formulauncertainty"
kind: system
layer: reasoning
currentness: changed-file
runtime_observed: false
certified: false
---
# Formula evaluation and local uncertainty

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Evaluates registered AST, finite-differences sensitivities and propagates supplied uncertainty/covariance.

## Historical source state

Numeric result, local derivative/uncertainty and supplied-case equivalence.

## Limits and unknowns

Perturbations can leave implicit mathematical domain; covariance check is pairwise plus one propagated variance, not full PSD validation.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1889]] — changed-file
- [[Evidence/S1888]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
