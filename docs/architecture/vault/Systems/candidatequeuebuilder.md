---
canonical_id: "candidatequeuebuilder"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# CSV and manifest candidate queue

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Combines map CSV and simple manifest scalar metadata into candidate/defer records.

## Historical source state

Candidate list and required-promotion declarations.

## Limits and unknowns

No actual admission; manifest-only records can omit checklist.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3434]] — same-file-bytes

## Directed relationships

- [[Systems/specialtymapbuilder]] — supplies candidate queue categories and IDs (`E1206`)
- [[Systems/countenvelopes]] — exposes candidate count invariant (`E1207`)
