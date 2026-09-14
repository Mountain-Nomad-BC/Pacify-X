---
canonical_id: "controlsourcebinding"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Current control-source evidence binding

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Hashes source files referenced by current proof matrix and requires exact receipt manifest equality.

## Historical source state

Current file hashes and manifest digest.

## Limits and unknowns

Does not independently bind current matrix policy or all source files.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3377]] — same-file-bytes

## Directed relationships

- [[Systems/directstageassembly]] — rejects absent or stale source manifests (`E1222`)
