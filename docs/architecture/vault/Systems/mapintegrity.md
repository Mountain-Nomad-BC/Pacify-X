---
canonical_id: "mapintegrity"
kind: system
layer: governance
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Project map full quick and freshness checks

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Validates selected artifact counts/hash entries/path restrictions and optionally rescans recorded source; quick status checks receipt metadata.

## Historical source state

Valid/errors/warnings, revision and labeled validation scope.

## Limits and unknowns

Full path does not enforce complete receipt hash inventory/self-hash; quick path does. Unavailable recorded root skips requested freshness with warning.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2664]] — same-file-bytes
- [[Evidence/S2662]] — same-file-bytes

## Directed relationships

- [[Systems/impacttrace]] — gates impact before reading graph files (`E551`)
