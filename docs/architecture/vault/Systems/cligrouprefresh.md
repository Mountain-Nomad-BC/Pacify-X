---
canonical_id: "cligrouprefresh"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# CLI owned stale-group refresh and custody

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Expands timeout to cover stale queue, launches one supervised child and reconciles newly unresolved resources.

## Historical source state

Fresh group outcomes, failed group denominator and scoped custody result.

## Limits and unknowns

Existing unresolved resources are outside the new-resource predicate; contained nonzero child relies on fresh receipts.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1736]] — changed-file

## Directed relationships

- [[Systems/cligroupexecution]] — launches supervised run-stale child (`E1373`)
- [[Systems/testprocesscustody]] — runs owned child with aggregate disk budget (`E1374`)
- [[Systems/testreceiptstatus]] — compares pre-run currentness and post-run freshness (`E1375`)
