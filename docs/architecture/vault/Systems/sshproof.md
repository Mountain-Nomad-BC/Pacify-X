---
canonical_id: "sshproof"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# SSH signing verification and feature probe

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Probes keygen/sign/verify features and supplies detached signature production and verification for local evidence and grants.

## Historical source state

Temporary files, subprocess checks and detached signature artifacts.

## Limits and unknowns

Verification has filesystem/process effects. Signing probe is uncached; later bare-name executable calls are not pinned to probe path. Signature authenticity alone does not establish semantic outcome.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2173]] — same-file-bytes
- [[Evidence/S2950]] — changed-file
- [[Evidence/S3263]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
