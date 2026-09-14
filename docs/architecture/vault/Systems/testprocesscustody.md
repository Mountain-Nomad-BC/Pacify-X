---
canonical_id: "testprocesscustody"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Managed test process workspace and validity

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Wraps ProcessSupervisor with pytest temp/key isolation and reclamation.

## Historical source state

Exit, timeout, tree closure and cleanup combined into valid.

## Limits and unknowns

Explicit basetemp can skip default custody; preparation before try and repeated exception cleanup remain.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3223]] — changed-file

## Directed relationships

- [[Systems/supervisor]] — supervises process and captures closure (`E845`)
- [[Systems/resources]] — creates and reclaims managed workspace (`E846`)
- [[Systems/pytestentry]] — loads explicit lifecycle plugin (`E1395`)
- [[Systems/pytestreclaim]] — supplies registered process-temp marker (`E1396`)
