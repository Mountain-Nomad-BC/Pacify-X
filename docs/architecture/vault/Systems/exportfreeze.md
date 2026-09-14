---
canonical_id: "exportfreeze"
kind: system
layer: evidence
currentness: changed-file
runtime_observed: false
certified: false
---
# Staged candidate byte records

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Hashes candidate files except manifest and links; compares frozen records before archive/replay.

## Historical source state

Candidate manifest and selected byte inventory.

## Limits and unknowns

Manifest itself, directory state and file links are outside frozen records.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3631]] — changed-file

## Directed relationships

- [[Systems/exportrebuild]] — optionally rebuilds staged candidate before sealing (`E1174`)
- [[Systems/exportreplay]] — compares frozen records before and after extraction (`E1179`)
