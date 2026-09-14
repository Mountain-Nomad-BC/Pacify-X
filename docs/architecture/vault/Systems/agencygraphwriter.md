---
canonical_id: "agencygraphwriter"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Agency graph output/check wrapper

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Writes or compares selected graph path then renders root-relative output label.

## Historical source state

Graph and valid result.

## Limits and unknowns

Outside-root absolute output may be written before relative-path summary raises.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3438]] — same-file-bytes

## Directed relationships

- [[Systems/graphprojection]] — separate graph publication entrypoint (`E1205`)
