---
canonical_id: "exactutilities"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Repository trace helper and generic wrapper

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

The exact runtime-path helper selects supplied event rows by serialized substring and timestamp sorting; the domain wrapper dispatches named outcomes to the generic suite.

## Historical source state

Selected event rows or normalized generic outcome result.

## Limits and unknowns

The helper name does not establish exact correlation-field matching or causal reconstruction. It silently skips malformed JSON and TypeError. A generic wrapper is distinct from independently implemented exact tools.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S008]] — same-file-bytes
- [[Evidence/S010]] — changed-file

## Directed relationships

- [[Systems/declared]] — dispatches generic script outcome (`E317`)
