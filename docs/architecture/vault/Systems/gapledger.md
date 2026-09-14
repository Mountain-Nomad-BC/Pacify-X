---
canonical_id: "gapledger"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Operational gap and work admission ledger

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Keeps append-only gap history, exact active checkpoints, effect scopes and session admission/closure.

## Historical source state

Chained events, compact head, gap cards, checkpoints and work sessions.

## Limits and unknowns

A pending mutating session excludes a new admission on that gap; this task encountered that boundary.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2562]] — changed-file
- [[Evidence/S2560]] — changed-file

## Directed relationships

- [[Systems/host]] — admits exact scoped effects (`E037`)
- [[Systems/dashboard]] — projects gap and control status (`E091`)
- [[Systems/repair]] — retains unresolved work before closure (`E112`)
