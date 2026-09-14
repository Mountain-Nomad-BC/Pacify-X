---
canonical_id: "indexentrypoints"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Semantic projection build entry points

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Two entry points call the same semantic index builder and serialize its result to an output file.

## Historical source state

Semantic index JSON and installed Python package aliases.

## Limits and unknowns

The builders entry point writes directly without creating its parent; the script creates the destination parent. Import aliases explain source runtime versus installed engineering_bootstrap identity.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S277]] — same-file-bytes
- [[Evidence/S3570]] — same-file-bytes
- [[Evidence/S1490]] — changed-file

## Directed relationships

- [[Systems/semanticprojection]] — builds and writes semantic index projection (`E324`)
