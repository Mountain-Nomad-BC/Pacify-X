---
canonical_id: "corpusfreezesnapshot"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Corpus one-pass freeze manifest

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Captures file content hashes and metadata for a caller comparison.

## Historical source state

Ordered tree digest with timestamped manifest.

## Limits and unknowns

No lock, second snapshot or pre-move equality check inside helper.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3722]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
