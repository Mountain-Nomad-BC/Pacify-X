---
canonical_id: "eventbusreplay"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Full ancestry scan and suffix selection

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Scans every event and validates chained envelopes before selecting the requested tail.

## Historical source state

Valid prefix count, selected suffix and errors.

## Limits and unknowns

No shared publish lock; empty event set bypasses state/head consistency check; limit bounds output only.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2479]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
