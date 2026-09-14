---
canonical_id: "pluginfixturebuilder"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Inert lifecycle fixture package builder

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Writes deterministic ZIP fixtures with fixed timestamps, CRC32 and v1/v2 extension identities.

## Historical source state

Two VSIX files and hash receipt.

## Limits and unknowns

Direct overwrite and late receipt are not crash-atomic; import executes builder; fixture activation has no operational work.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S475]] — same-file-bytes
- [[Evidence/S1415]] — same-file-bytes
- [[Evidence/S1416]] — same-file-bytes

## Directed relationships

- [[Systems/extensionnativeeffect]] — supplies inert lifecycle packages (`E1466`)
