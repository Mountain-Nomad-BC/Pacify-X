---
canonical_id: "efficiencymeasurement"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Fixture scan and single-flight measurement

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Measures four synthetic filesystem profiles and one hundred joined governor requests.

## Historical source state

Duration/lag/capping and duplicate-execution acceptance fields.

## Limits and unknowns

Rejected scan leaves interval running; fixture construction is outside timing; zero heartbeat ticks can still pass.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S482]] — same-file-bytes
- [[Evidence/S1450]] — same-file-bytes

## Directed relationships

- [[Systems/hostgovernor]] — measures one hundred same-key joins (`E1470`)
- [[Systems/environment]] — scans four synthetic roots (`E1471`)
