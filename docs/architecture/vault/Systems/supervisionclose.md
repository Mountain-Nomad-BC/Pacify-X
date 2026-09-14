---
canonical_id: "supervisionclose"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# OS containment and supervisor closure

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Assigns suspended Windows child to kill-on-close Job; tracks sampled POSIX descendants and fingerprints, shuts down and records closure.

## Historical source state

Job active-process count or tracked descendant proof, resource closure and separate receipt.

## Limits and unknowns

Unexpected callback failures can leave no normal result/receipt; POSIX finally does not guarantee shutdown. POSIX discovery can miss descendants between samples. Persisted reconciliation reports root absence as tree_closed.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2626]] — changed-file
- [[Evidence/S2622]] — changed-file
- [[Evidence/S2623]] — changed-file

## Directed relationships

- [[Systems/resourcecustody]] — publishes process resource disposition (`E452`)
