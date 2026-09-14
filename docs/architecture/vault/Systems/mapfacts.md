---
canonical_id: "mapfacts"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Project fact cache and language scanners

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Reuses declared hash/version facts or scans bounded source using Python AST, language regex and config-specific parsers.

## Historical source state

Per-file symbols/imports/calls/routes/config names/contracts/services/parse errors.

## Limits and unknowns

Prior facts are not authenticated before reuse; text scan limit omitted from reuse key. Language support and retained values differ by scanner.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2655]] — same-file-bytes
- [[Evidence/S2646]] — same-file-bytes
- [[Evidence/S2657]] — same-file-bytes
- [[Evidence/S2648]] — same-file-bytes

## Directed relationships

- [[Systems/mapinference]] — derives static relationships (`E547`)
