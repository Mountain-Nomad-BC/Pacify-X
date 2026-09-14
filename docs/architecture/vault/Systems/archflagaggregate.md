---
canonical_id: "archflagaggregate"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Architecture invariant predicate aggregation

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Combines13 exact-True flags and an optional tree metadata validator.

## Historical source state

Stable failed-ID report.

## Limits and unknowns

Some named predicates check existence/truthiness; tree helper registered but no authored caller found.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1607]] — same-file-bytes

## Directed relationships

- [[Systems/coordvectors]] — counts vector-file existence as conformance predicate (`E626`)
- [[Systems/topologydecl]] — checks declared effect topology (`E627`)
- [[Systems/primitivedecl]] — checks complete primitive declarations (`E628`)
- [[Systems/maturityladder]] — checks maturity policy metadata (`E632`)
