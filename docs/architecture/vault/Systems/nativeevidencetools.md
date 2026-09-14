---
canonical_id: "nativeevidencetools"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Native ingestion trace and replay helpers

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Checks UTF-8 text sanity, appends supplied span metadata and writes file-hash replay manifests.

## Historical source state

Text/hash facts, supplied spans and replay instructions.

## Limits and unknowns

Trace IDs can repeat for identical supplied fields. A replay manifest does not copy or restore bytes, execute replay, redact data or validate later outcomes.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S194]] — same-file-bytes
- [[Evidence/S199]] — same-file-bytes
- [[Evidence/S196]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
