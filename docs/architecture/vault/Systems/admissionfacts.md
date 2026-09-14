---
canonical_id: "admissionfacts"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Authenticated admission fact derivation

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Resolves provenance, license, tests and security evidence, derives boolean facts and classifies manifest disposition.

## Historical source state

Admit or restrict can be accepted authoritatively; compatibility review remains nonauthoritative.

## Limits and unknowns

Scope binds candidate ID/project, not version/content. Authenticated security result with no malicious_or_unsafe true value is treated as not malicious.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1506]] — changed-file
- [[Evidence/S1505]] — changed-file

## Directed relationships

- [[Systems/signedresolver]] — authenticates four admission evidence types (`E471`)
