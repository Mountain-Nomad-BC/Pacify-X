---
canonical_id: "cliinputpublication"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# CLI input size and projection effects

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Publishes bounded event batches and placement artifacts, and loads many caller JSON inputs.

## Historical source state

Event/placement/report outputs and loaded payloads.

## Limits and unknowns

Most JSON files are read unbounded; placement publication has no apply flag; event bus root is caller-selected.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1720]] — changed-file
- [[Evidence/S1737]] — changed-file
- [[Evidence/S1744]] — changed-file
- [[Evidence/S1831]] — changed-file

## Directed relationships

- [[Systems/telemetry]] — publishes operation batch at caller bus root (`E1387`)
- [[Systems/placementpublish]] — always publishes placement result artifact (`E1388`)
