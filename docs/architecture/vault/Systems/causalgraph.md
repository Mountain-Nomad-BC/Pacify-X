---
canonical_id: "causalgraph"
kind: system
layer: reasoning
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Causal DAG separation and path analysis

[[Layers/reasoning]] · [[Views/Full_Architecture]]

## Purpose

Validates DAG endpoints/cycles and computes moral-graph separation, backdoor checks and bounded paths.

## Historical source state

Graph-relative validity and paths.

## Limits and unknowns

Caller graph is an assumption; path enumeration does not report whether limits hid more paths.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1871]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
