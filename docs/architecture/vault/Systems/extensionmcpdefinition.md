---
canonical_id: "extensionmcpdefinition"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# MCP server definition and host launch authority

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Uses SecretStorage key to sign project/session launch authority and supplies bundle/env to VS Code.

## Historical source state

Definition provider, public JWK file and registered_unverified state.

## Limits and unknowns

Existing JWK file is trusted for reuse without local byte comparison; provider registration is not server health.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1059]] — changed-file

## Directed relationships

- [[Systems/mcplaunch]] — provides signed process definition (`E1499`)
