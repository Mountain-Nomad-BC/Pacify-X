---
canonical_id: "coordpublish"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Coordination state publication sequence

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Locks the store, verifies previous state and event tail, mutates in memory, validates the transition, then publishes deferred files, state, event, receipt and handoff.

## Historical source state

Before/after hashes, event predecessor/hash, current state and separate receipt/handoff files.

## Limits and unknowns

These are ordered writes to multiple files. This function is not a cross-file atomic transaction; a mid-publication interruption needs owner-specific diagnosis.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S944]] — changed-file
- [[Evidence/S1262]] — changed-file

## Directed relationships

- [[Systems/coordinvariants]] — validates prior state before expiry normalization (`E364`)
- [[Systems/coordresume]] — publishes handoff after state event and receipt (`E365`)
