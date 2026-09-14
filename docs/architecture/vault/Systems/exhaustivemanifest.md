---
canonical_id: "exhaustivemanifest"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Exhaustive walk source manifest

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Hashes distinct declared control source paths before browser work.

## Historical source state

Manifest files and canonical digest.

## Limits and unknowns

Only declared paths; ancestor links, concurrent source changes and unlisted preview/harness assets are not closed.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S579]] — changed-file

## Directed relationships

- [[Systems/exhaustiveresume]] — supplies current manifest to resume predicate (`E1547`)
