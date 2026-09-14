---
canonical_id: "mcplaunch"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# VS Code MCP launch definition

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Creates a workspace-bound signed launch and registers a host-started Node stdio server definition.

## Historical source state

Definition command, workspace roots, public-key path, signed claim and launch token.

## Limits and unknowns

Definition registration is not invocation. The provider callback can create a public-key file. It passes an empty context path; no actual host launch was performed in this report.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1060]] — changed-file

## Directed relationships

- [[Systems/mcpbundle]] — points Node at generated server/index.js (`E328`)
- [[Systems/bundlestdio]] — starts deployed stdio adapter (`E1615`)
