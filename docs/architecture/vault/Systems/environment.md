---
canonical_id: "environment"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# Environment discovery and inventory generations

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Probes admitted tools and packages, scans admitted roots and publishes environment inventory generations or returns a memory-only discovery result.

## Historical source state

Tool/package/environment metadata, generation manifest, freshness and optional persistence event.

## Limits and unknowns

Discovery availability is not installed-system acceptance. Source code was inspected; no environment scan was launched for this atlas.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S983]] — same-file-bytes
- [[Evidence/S3236]] — changed-file
- [[Evidence/S3232]] — changed-file
- [[Evidence/S986]] — same-file-bytes

## Directed relationships

- [[Systems/envlifecycle]] — supplies selected resource records for preview (`E182`)
