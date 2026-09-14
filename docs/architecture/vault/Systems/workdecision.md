---
canonical_id: "workdecision"
kind: system
layer: scope
currentness: changed-file
runtime_observed: false
certified: false
---
# Work reservation and job decision functions

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Computes all-dimension budget admission, version-checked lease decisions, runtime eligibility and sticky job transitions from caller snapshots.

## Historical source state

Returned reservation, lease, placement and transition records.

## Limits and unknowns

The atomic/CAS wording describes a decision over supplied state. These functions contain no shared-state transaction, lock, scheduler or process termination.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1938]] — changed-file
- [[Evidence/S1937]] — changed-file
- [[Evidence/S1930]] — changed-file
- [[Evidence/S1931]] — changed-file
- [[Evidence/S1940]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
