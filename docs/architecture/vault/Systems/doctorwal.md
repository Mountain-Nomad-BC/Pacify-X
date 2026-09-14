---
canonical_id: "doctorwal"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Doctor selected WAL recovery inspection

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Configures five existing WAL roots and invokes reconciliation with apply false.

## Historical source state

Recovery status and selected-root count.

## Limits and unknowns

Not discovery of every WAL owner; no known roots is degraded.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2749]] — changed-file

## Directed relationships

- [[Systems/recoverypass]] — calls recovery reconciliation with apply false (`E1154`)
