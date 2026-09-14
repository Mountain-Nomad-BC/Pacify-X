---
canonical_id: "mappromotion"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Project map staging archive and publication

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Writes nineteen artifacts under unique stage, validates staged map, archives previous output, promotes stage then rewrites final receipt.

## Historical source state

Promoted map, previous/failed/lock histories and work-plane admission receipt.

## Limits and unknowns

Two renames leave a replacement gap; no restore-old branch if promotion fails. Final receipt publication and lock history are separate effects.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2648]] — same-file-bytes
- [[Evidence/S2661]] — same-file-bytes

## Directed relationships

- [[Systems/mapintegrity]] — checks prepared stage before rename (`E550`)
- [[Systems/archivecustody]] — retains previous snapshot for optional archive helper (`E553`)
