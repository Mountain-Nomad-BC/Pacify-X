---
canonical_id: "summary"
kind: system
layer: memory
currentness: changed-file
runtime_observed: false
certified: false
---
# Incremental session summaries

[[Layers/memory]] · [[Views/Full_Architecture]]

## Purpose

Consumes events after a saved cursor, retains bounded distinct statements and writes an immutable checkpoint or final summary.

## Historical source state

Session-scoped numbered summary JSON, processed cursor and source hash.

## Limits and unknowns

This is extractive sentence selection. No production automatic session-to-vault adapter was located in the runtime/extension call-site sweep.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2376]] — changed-file

## Directed relationships

- [[Systems/capture]] — offers a bounded session summary (`E161`)
- [[Systems/summarycursor]] — owns pending event cursor and extractive checkpoint (`E670`)
