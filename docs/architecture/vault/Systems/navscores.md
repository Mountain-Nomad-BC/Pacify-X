---
canonical_id: "navscores"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Navigation metadata and score adaptation

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Adapts core contracts, skill packages, semantic records, cognitive metadata and agency labels into CapabilitySummary fields.

## Historical source state

Risk/status/quality/coverage metadata used by ranking.

## Limits and unknowns

Some scores derive from file existence, label/hash presence or constants; core risk is inferred from effects rather than contract risk.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2795]] — changed-file
- [[Evidence/S2798]] — changed-file
- [[Evidence/S2794]] — changed-file

## Directed relationships

- [[Systems/semanticbuildio]] — loads stored semantic records for navigation (`E635`)
