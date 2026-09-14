---
canonical_id: "bundleworkerpaths"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# Bundled worker relative-path contract

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Retains exported async helper constructors using __dirname-relative worker scripts.

## Historical source state

Computed server/teamFabricWorker.js and server/discoveryWorker.js paths.

## Limits and unknowns

Those files exist under src, not server; current MCP routes use synchronous/read functions, so this is a dormant exported-helper deployment gap.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S794]] — changed-file
- [[Evidence/S803]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
