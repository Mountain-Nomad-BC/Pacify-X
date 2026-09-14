---
canonical_id: "securitypackprojection"
kind: system
layer: acquisition
currentness: changed-file
runtime_observed: false
certified: false
---
# Pinned archive companion metadata projection

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Pins archive but imports separate catalog/graph/domain/workflow/pack metadata.

## Historical source state

Discovery-only provider and companion source records.

## Limits and unknowns

Archive pin does not authenticate independently supplied companion files.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3460]] — changed-file

## Directed relationships

- [[Systems/securitymetadata]] — publishes candidate metadata for runtime validation (`E1211`)
- [[Systems/securityreference]] — declares external archive supplied to explicit hydration (`E1212`)
- [[Systems/securitycontractprojection]] — precedes projected operational contracts (`E1213`)
