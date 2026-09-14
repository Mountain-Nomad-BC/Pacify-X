---
canonical_id: "securitymetadata"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Deferred security catalog and lexical discovery

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Checks selected provider invariants and scores metadata-only candidates.

## Historical source state

Candidate ranking and golden expected-domain report.

## Limits and unknowns

Known source digest is a declaration until archive hydration checks actual bytes.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1978]] — changed-file

## Directed relationships

- [[Systems/securitypackage]] — ranks at most 100 candidates first (`E1115`)
- [[Systems/securityreference]] — supplies expected source path and body hash (`E1119`)
