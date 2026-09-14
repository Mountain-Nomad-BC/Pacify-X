---
canonical_id: "coveragecounts"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Executed coverage report policy check

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Reads coverage JSON and policy, aggregates declared branch totals and checks context labels.

## Historical source state

Class percentages, report/policy hashes and errors.

## Limits and unknowns

No source-derived branch denominator or numeric sanity check; release caller owns actual generation.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1960]] — changed-file

## Directed relationships

- [[Systems/certificate]] — binds report bytes under release root (`E745`)
