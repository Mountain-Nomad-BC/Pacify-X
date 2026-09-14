---
canonical_id: "transcripts"
kind: system
layer: acquisition
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Transcript extraction and ontology records

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Plans selected transcript intake, validates source-bound canonical extraction records and exports explicitly selected conversation summaries.

## Historical source state

Run-local source inventory, extraction records, ontology terms and selected CSV.

## Limits and unknowns

Here canonical refers to the transcript extraction schema. It does not mean Memory Vault certification or Knowledge Core authority.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3259]] — same-file-bytes
- [[Evidence/S3260]] — same-file-bytes
- [[Evidence/S3258]] — same-file-bytes

## Directed relationships

- [[Systems/research]] — offers source-bound extracted records (`E171`)
- [[Systems/transcriptadapterplan]] — offers profile and adapter planning entrypoint (`E1092`)
- [[Systems/transcriptcustody]] — dispatches independent ingest command (`E1093`)
- [[Systems/transcriptsummary]] — dispatches selected export command (`E1098`)
