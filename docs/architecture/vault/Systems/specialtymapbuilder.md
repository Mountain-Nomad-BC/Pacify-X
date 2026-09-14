---
canonical_id: "specialtymapbuilder"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Specialty activation metadata projection

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Categorizes queue entries and marks active membership using catalog status.

## Historical source state

Specialty categories and represented-ID counts.

## Limits and unknowns

Duplicate category rows can disagree with deduplicated counts; active label is declared.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3571]] — same-file-bytes

## Directed relationships

- [[Systems/countenvelopes]] — exposes nested category count invariants (`E1208`)
