---
canonical_id: "iwprojects"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Project initialization and graph build observations

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Visits build entry points, cancels/executes build and compares map identity across restart.

## Historical source state

Map revision, inventory hash and count tuple.

## Limits and unknowns

Shared cancellation/build evidence and metadata equality are narrower than independent entrypoint and graph-byte proof.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S773]] — changed-file

## Directed relationships

- [[Systems/iwgraphidentity]] — compares map and graph projections (`E1585`)
