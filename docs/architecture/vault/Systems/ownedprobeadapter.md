---
canonical_id: "ownedprobeadapter"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Owned host profile stage adapter

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Validates source-bound probe shape and combines compatible profile stages.

## Historical source state

Direct current-source or installed stage receipt.

## Limits and unknowns

Evidence kind is caller-selected; no installed artifact check in this adapter.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3517]] — same-file-bytes

## Directed relationships

- [[Systems/controlsourcebinding]] — requires walk source manifest equality (`E1224`)
- [[Systems/directstageassembly]] — exports merged host profile stages (`E1226`)
- [[Systems/stageevidencepublication]] — writes adapted profile receipt (`E1229`)
