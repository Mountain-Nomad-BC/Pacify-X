---
canonical_id: "semanticbuildio"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Semantic index source and overlay assembly

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Reads catalog/contracts/bodies into compact records and verifies exact rebuild equality.

## Historical source state

Profile/body/contract digests and whole index revision.

## Limits and unknowns

Alias/workflow inputs bypass overlays; no atomic source snapshot or loader freshness check.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3007]] — same-file-bytes

## Directed relationships

- [[Systems/semanticprofilebuild]] — normalizes each catalog entry with maturity unset (`E633`)
