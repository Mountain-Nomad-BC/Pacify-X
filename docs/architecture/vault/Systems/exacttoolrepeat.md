---
canonical_id: "exacttoolrepeat"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Normalized helper repeat comparison

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Compares stdout and output-file hashes after removing selected volatile values and fixture paths.

## Historical source state

Deterministic-repeat flag and inferred coverage classes.

## Limits and unknowns

Broad substring-based field removal can hide meaningful differences.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2108]] — same-file-bytes
- [[Evidence/S2128]] — same-file-bytes

## Directed relationships

- [[Systems/exacttoolaggregate]] — contributes repeat and coverage labels (`E1130`)
