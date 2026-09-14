---
canonical_id: "sourcearchivemembers"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Git archive member and budget checks

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Checks tar physical/declared size and required/forbidden regular-file names.

## Historical source state

Membership result and counts.

## Limits and unknowns

Does not hash archive or validate duplicate/path/link/content semantics.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3414]] — same-file-bytes

## Directed relationships

- [[Systems/sourcearchiveclosure]] — retains membership result then reconciles workspace (`E1182`)
