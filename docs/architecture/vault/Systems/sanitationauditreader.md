---
canonical_id: "sanitationauditreader"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Identifier audit traversal and content classification

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Scans configured identifier/home patterns in admitted text and records ZIP paths.

## Historical source state

Hit offsets, file/byte counters and selected read errors.

## Limits and unknowns

Full rglob materialization precedes exclusions; unknown-suffix read errors can become binary classification without an error.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3406]] — same-file-bytes

## Directed relationships

- [[Systems/sanitationauditgates]] — projects hits into scoped gates (`E1434`)
