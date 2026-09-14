---
canonical_id: "startupreads"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Startup metadata and retained state reads

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Loads config, coordination state checks, registry/policy/model/project/catalog metadata.

## Historical source state

StartupSnapshot without hydrated skills.

## Limits and unknowns

Record limits after loads; configured coordination checks include retained memory and events.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3056]] — changed-file

## Directed relationships

- [[Systems/worldfresh]] — loads projection before detailed startup metadata (`E603`)
- [[Systems/pycoordstartup]] — checks configured retained coordination state (`E605`)
- [[Systems/navscores]] — loads core navigation metadata (`E606`)
- [[Systems/startupprobes]] — runs candidate resolver pool (`E607`)
