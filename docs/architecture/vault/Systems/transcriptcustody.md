---
canonical_id: "transcriptcustody"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Transcript source planning and copied run custody

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Inventories sources, hashes copies and publishes new staged run directory.

## Historical source state

Source receipts and run manifest.

## Limits and unknowns

Metadata limits checked before full reads; links/duplicates and publication races remain.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3239]] — same-file-bytes

## Directed relationships

- [[Systems/transcriptrecords]] — supplies source manifest for record binding (`E1094`)
