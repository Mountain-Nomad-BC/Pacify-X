---
canonical_id: "proposalidentity"
kind: system
layer: acquisition
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Sanitized proposal identity

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Validates IDs, sanitizes nested values and hashes candidate envelopes.

## Historical source state

Candidate metadata and digest.

## Limits and unknowns

Identity is of sanitized data; recursion and input collection materialization are not bounded.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S254]] — same-file-bytes
- [[Evidence/S253]] — same-file-bytes

## Directed relationships

- [[Systems/proposalpublication]] — caller may explicitly write candidate (`E783`)
