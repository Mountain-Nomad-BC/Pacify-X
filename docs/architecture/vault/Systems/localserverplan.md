---
canonical_id: "localserverplan"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Local server plan and startup acceptance

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Constructs exact loopback command and self-hashed plan, then rechecks plan and artifact digests before spawning.

## Historical source state

ServerPlan and owned process registration.

## Limits and unknowns

Start does not reconstruct command or repeat constructor root/host/range checks; unkeyed self-consistency is not a work admission.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2343]] — changed-file
- [[Evidence/S2345]] — changed-file

## Directed relationships

- [[Systems/resourcecustody]] — starts and registers server process (`E520`)
- [[Systems/localreadiness]] — polls after owned process spawn (`E521`)
