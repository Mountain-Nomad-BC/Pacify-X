---
canonical_id: "mcpbundle"
kind: system
layer: release
currentness: changed-file
runtime_observed: false
certified: false
---
# Generated MCP deployment bundle

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Bundles server/source.mjs and its dependency graph into server/index.js as Node 20 CommonJS with substituted package version.

## Historical source state

Generated deployment bytes; 4,383 extracted functions include copied dependencies and PX implementation.

## Limits and unknowns

Version equality is weaker than a fresh entire-bundle rebuild comparison. Raw source and compiled bundle are distinct identities; this report did not run the builder.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S474]] — same-file-bytes
- [[Evidence/S528]] — same-file-bytes
- [[Evidence/S471]] — changed-file

## Directed relationships

- [[Systems/bundleorigins]] — contains generated and dependency origins (`E1612`)
