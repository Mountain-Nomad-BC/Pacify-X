---
canonical_id: "preflightstatic"
kind: system
layer: release
currentness: changed-file
runtime_observed: false
certified: false
---
# Ordered preflight static gates

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Runs DAG, feedback, portability, budget, skip policy, repository context, groups and completion projection.

## Historical source state

First failing gate stops later checks.

## Limits and unknowns

Static includes a live completion projection write; discovery does not exhaust all gates.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2947]] — changed-file

## Directed relationships

- [[Systems/preflightbinding]] — captures binding before static checks (`E828`)
- [[Systems/completionprojection]] — publishes current test completion projection (`E829`)
- [[Systems/preflightcache]] — loads expensive results after static success (`E830`)
- [[Systems/preflightreceipt]] — returns and optionally stores readiness result (`E837`)
