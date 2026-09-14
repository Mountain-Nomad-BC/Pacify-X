---
canonical_id: "starterversionrecovery"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Starter immutable version conflict recovery

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Checks identity absence, may establish initial revision, allocates current candidate version and retries create.

## Historical source state

Candidate revision and creation result.

## Limits and unknowns

Finite retry path; code/reason or selected traceback matching differs from strict draft conflict classifier.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1272]] — same-file-bytes

## Directed relationships

- [[Systems/versionallocation]] — requests fresh physical candidate version (`E1021`)
