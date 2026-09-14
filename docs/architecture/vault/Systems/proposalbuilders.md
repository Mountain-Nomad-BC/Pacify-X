---
canonical_id: "proposalbuilders"
kind: system
layer: acquisition
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Candidate proposal builders

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Constructs bounded skill, repair-pattern, adapter, test-evidence and orchestration proposals from supplied metadata. Narrow adapter transform performs validated field mapping.

## Historical source state

Candidate envelopes, digests, declared evidence steps and nonactivation flags.

## Limits and unknowns

A supplied registry or passed test field is not an independently resolved complete registry or a fresh test run. Candidate publication checks destination absence before writing; it is not an exclusive atomic publish.

## Historical suggested evolution

Candidate artifacts can inform separately admitted capability changes; generation itself does not activate them.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S280]] — same-file-bytes
- [[Evidence/S275]] — same-file-bytes
- [[Evidence/S250]] — same-file-bytes
- [[Evidence/S245]] — same-file-bytes
- [[Evidence/S283]] — same-file-bytes
- [[Evidence/S271]] — same-file-bytes

## Directed relationships

- [[Systems/admission]] — produces inert candidate for separate review (`E316`)
- [[Systems/proposalidentity]] — groups candidate construction helpers (`E782`)
