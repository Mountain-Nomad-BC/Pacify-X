---
canonical_id: "hybridadapter"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Portable hybrid retrieval adapter

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Converts explicit JSON corpus records into RetrievalSource objects and calls the same retrieval kernel in source and installed-package modes.

## Historical source state

Corpus adapter, selected scope, bounded hits and canonical-owner result.

## Limits and unknowns

The concrete adapter was outside runtime/. Its existence does not establish universal Agent Studio or Memory Vault dispatch.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S193]] — same-file-bytes
- [[Evidence/S4224]] — same-file-bytes

## Directed relationships

- [[Systems/retrievalcore]] — delegates corpus ranking to canonical kernel (`E174`)
