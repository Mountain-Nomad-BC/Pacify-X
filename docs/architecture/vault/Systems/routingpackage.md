---
canonical_id: "routingpackage"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Greedy capability package and dependency closure

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Selects scored candidates under kind/total budgets, adds dependencies and collects contract/validator IDs.

## Historical source state

complete/executable metadata flags, dependency list and package digest.

## Limits and unknowns

Dependency append does not rerun lifecycle/risk/reviewer filters. Complete does not require all capability terms covered; executable excludes agent kind but grants no authority.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1667]] — changed-file

## Directed relationships

- [[Systems/planidentity]] — compiles descriptive plan regardless of complete flag (`E502`)
