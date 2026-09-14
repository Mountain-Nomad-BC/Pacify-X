---
canonical_id: "certreadinessengine"
kind: system
layer: governance
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Managed campaign versus unmanaged engine readiness

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Uses managed campaign phase without rerun; otherwise launches validation subprocess.

## Historical source state

Engine prerequisite status.

## Limits and unknowns

Campaign declaration checks do not authenticate current validation receipts.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1688]] — same-file-bytes

## Directed relationships

- [[Systems/testphaseadmission]] — reads campaign phase without rerunning managed validation (`E1124`)
