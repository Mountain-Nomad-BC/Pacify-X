---
canonical_id: "transcriptruncheck"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Transcript run integrity validation

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Checks copied-source hashes, record schemas and manifest/record digests.

## Historical source state

Integrity result with counts.

## Limits and unknowns

Does not repeat all provenance/uniqueness checks performed by writer.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3248]] — same-file-bytes

## Directed relationships

- [[Systems/transcriptsummary]] — gates summary then allows independent rereads (`E1096`)
