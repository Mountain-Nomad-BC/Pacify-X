---
canonical_id: "certificationsign"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Detached certificate signature and trust policy

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Canonicalizes signed payload and verifies OpenSSH namespace/publisher/trusted signer.

## Historical source state

Certificate content hash and detached signature.

## Limits and unknowns

Tool subprocess and temporary custody separate from governed test runner; policy is local trust authority.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2951]] — changed-file
- [[Evidence/S2952]] — changed-file

## Directed relationships

- [[Systems/certificationcommit]] — journals and copies signed evidence (`E850`)
