---
canonical_id: "package"
kind: system
layer: release
currentness: changed-file
runtime_observed: false
certified: false
---
# Exact package and installed identity

[[Layers/release]] · [[Views/Full_Architecture]]

## Purpose

Builds/verifies artifacts, binds exact bytes to source identity and installs the selected wheel or VSIX through owned paths.

## Historical source state

Artifact manifest, package digest, file inventory and installation identity.

## Limits and unknowns

A package existing on disk is not installed-system operational proof.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2906]] — changed-file
- [[Evidence/S2905]] — changed-file
- [[Evidence/S528]] — same-file-bytes
- [[Evidence/S2039]] — changed-file
- [[Evidence/S2331]] — changed-file
- [[Evidence/S2918]] — same-file-bytes
- [[Evidence/S2917]] — same-file-bytes
- [[Evidence/S2949]] — same-file-bytes
- [[Evidence/S2940]] — changed-file
- [[Evidence/S2948]] — changed-file

## Directed relationships

- [[Systems/operational]] — provides exact installed artifact (`E107`)
- [[Systems/certificate]] — binds exact artifact hashes (`E110`)
- [[Systems/mcpbundle]] — includes existing MCP bundle in VSIX (`E330`)
