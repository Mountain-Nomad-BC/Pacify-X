---
canonical_id: "graphprojection"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Registry graph construction and byte comparison

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Builds contract, asset and ordered project-stream projections and derives a source/output hash manifest.

## Historical source state

Six graph artifacts; validator requires exact file set and bytes.

## Limits and unknowns

Source hashes are reread after graph construction; publication is sequential. Declared executes edges are metadata.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2218]] — same-file-bytes
- [[Evidence/S3187]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
