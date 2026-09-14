---
canonical_id: "controlpolicies"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Operational policy evaluators

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Evaluates memory, bundles, supply chain, loop progress, impact, research completeness, progress, compilation and topology from supplied payloads.

## Historical source state

Typed ControlResult with decision, reasons, computed details and supplied evidence references.

## Limits and unknowns

candidate_compiled selects IDs marked verified with evidence; it is not executable process compilation or independent verification of those claims.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2472]] — changed-file
- [[Evidence/S2470]] — changed-file
- [[Evidence/S2468]] — changed-file
- [[Evidence/S2466]] — changed-file

## Directed relationships

- [[Systems/process]] — filters evidence-marked candidate records (`E167`)
- [[Systems/research]] — checks research fields and control gaps (`E168`)
- [[Systems/engineeringdispatch]] — routes operational skill request (`E957`)
