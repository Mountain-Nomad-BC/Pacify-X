---
canonical_id: "directstageassembly"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Direct control-stage receipt assembly

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Combines allowed receipt kinds, stage policies and per-control observations.

## Historical source state

Assembled stage chains, authority references and counts.

## Limits and unknowns

Declared kind/reference semantics and cross-run compatibility are not authenticated here.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3378]] — same-file-bytes

## Directed relationships

- [[Systems/stageevidencepublication]] — writes assembled control chains (`E1227`)
