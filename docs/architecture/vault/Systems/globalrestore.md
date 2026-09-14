---
canonical_id: "globalrestore"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Original global skill restoration

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Checks custody and empty target, then moves original tree back.

## Historical source state

Original tree and selected manifest.

## Limits and unknowns

No restore lock, prepared journal or generation merge.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2217]] — same-file-bytes

## Directed relationships

- [[Systems/globalmanifestcustody]] — restores manifest after tree move (`E898`)
