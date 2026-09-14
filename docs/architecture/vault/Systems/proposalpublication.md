---
canonical_id: "proposalpublication"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Candidate proposal file publication

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Writes candidate JSON after kind/id and nonactivation checks.

## Historical source state

Proposal file in caller output directory.

## Limits and unknowns

Does not verify digest; existence check and write are separate, without exclusive create or atomic publication.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S255]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
