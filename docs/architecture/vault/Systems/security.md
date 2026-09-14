---
canonical_id: "security"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Security and external tool governance

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Selects security capabilities, checks authority and treats external tools as inspectable candidates before activation.

## Historical source state

Security decisions, quarantined/tool intake records and provenance.

## Limits and unknowns

A security catalog does not imply that every external tool is installed or callable.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1979]] — changed-file
- [[Evidence/S3228]] — same-file-bytes
- [[Evidence/S3006]] — changed-file
- [[Evidence/S2999]] — changed-file

## Directed relationships

- [[Systems/external]] — constrains intake before execution (`E070`)
