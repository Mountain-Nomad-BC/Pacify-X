---
canonical_id: "nativesecuritytools"
kind: system
layer: governance
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Native policy and supply-chain helpers

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Produces policy profiles, manifest/BOM/provenance records, fixed threat patterns, regex input signals and policy decisions; one adapter calls the canonical secret scanner.

## Historical source state

Explicit CLI inputs, structured results and selected output files.

## Limits and unknowns

Profiles and approval identifiers are supplied declarations, not active sandbox enforcement or signed authority. Provenance records claimed commands without executing them.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S224]] — same-file-bytes
- [[Evidence/S225]] — same-file-bytes
- [[Evidence/S226]] — same-file-bytes
- [[Evidence/S227]] — same-file-bytes
- [[Evidence/S228]] — same-file-bytes
- [[Evidence/S229]] — same-file-bytes
- [[Evidence/S230]] — same-file-bytes
- [[Evidence/S231]] — same-file-bytes
- [[Evidence/S232]] — same-file-bytes

## Directed relationships

- [[Systems/secretshapes]] — delegates secret scanning to canonical implementation (`E357`)
