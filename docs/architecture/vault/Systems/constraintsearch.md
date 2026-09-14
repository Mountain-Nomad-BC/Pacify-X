---
canonical_id: "constraintsearch"
kind: system
layer: reasoning
currentness: changed-file
runtime_observed: false
certified: false
---
# Finite-domain backtracking search

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Orders variables by domain size and prunes inconsistent partial assignments under node/solution budgets.

## Historical source state

Solutions, rejection counts and budget/truncation flags.

## Limits and unknowns

Malformed nonmapping constraints are dropped; satisfiable false with exhausted budget is inconclusive.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1877]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
