---
canonical_id: "doctorclicontract"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# Doctor CLI requested readiness contract

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Selects syntax/operable/ready/certification-ready predicate to control process exit.

## Historical source state

Default operable; exit 0 when satisfied, otherwise 2.

## Limits and unknowns

CLI projection adds fields beyond hashed base report; syntax success is not readiness.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1843]] — changed-file
- [[Evidence/S1727]] — changed-file
- [[Evidence/S1840]] — changed-file

## Directed relationships

- [[Systems/doctorcompose]] — consumes separate report readiness predicates (`E1148`)
