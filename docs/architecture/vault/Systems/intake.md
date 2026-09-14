---
canonical_id: "intake"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Stable intake and quarantine

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Tracks open intake, full-tree snapshots and pre-move equality before closed stable intake can be quarantined.

## Historical source state

Intake events, matching snapshots and quarantine receipt.

## Limits and unknowns

Open intake is not eligible for final sanitization/quarantine.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2256]] — same-file-bytes
- [[Evidence/S2255]] — same-file-bytes
- [[Evidence/S2251]] — same-file-bytes
- [[Evidence/S2216]] — same-file-bytes

## Directed relationships

- [[Systems/resources]] — requires stable custody before quarantine (`E103`)
