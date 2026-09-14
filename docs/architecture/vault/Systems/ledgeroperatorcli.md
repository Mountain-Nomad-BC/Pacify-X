---
canonical_id: "ledgeroperatorcli"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Operational ledger operator CLI

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Routes explicit operator commands and separate work guard to ledger APIs.

## Historical source state

JSON output or exception.

## Limits and unknowns

Mutation commands do not automatically invoke work guard.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3801]] — same-file-bytes

## Directed relationships

- [[Systems/ledgerappendplanner]] — routes event mutation commands (`E1233`)
- [[Systems/ledgerworkguard]] — checks explicitly requested work scope (`E1234`)
- [[Systems/ledgercheckpointreader]] — reads compact progress or exact admission projection (`E1235`)
