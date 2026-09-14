---
canonical_id: "candidatepipeline"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Candidate filtering and package utility

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Checks an eleven-stage trace, compares supplied intrinsic score tables, and greedily chooses admitted candidates before adding dependencies.

## Historical source state

Trace hash, selected IDs, rejected reasons, declared cost and completeness.

## Limits and unknowns

This evaluates supplied records; it does not invoke candidate components, verify signed admission, or solve a global optimum.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1941]] — changed-file
- [[Evidence/S1944]] — changed-file
- [[Evidence/S1935]] — changed-file

## Directed relationships

- [[Systems/candidatephasetrace]] — offers trace validation API (`E975`)
