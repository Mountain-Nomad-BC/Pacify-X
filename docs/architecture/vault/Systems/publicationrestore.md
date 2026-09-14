---
canonical_id: "publicationrestore"
kind: system
layer: durability
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Signed publication verification and restoration

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Verifies custody and inner certificate, exact VSIX/summary/Python artifacts and restores release evidence tree.

## Historical source state

Verified identities plus repository release-tree write.

## Limits and unknowns

Verification performs extraction and publication; optional replacement deletes backup after new target commits. Failure can leave extracted output or committed target.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S4051]] — same-file-bytes

## Directed relationships

- [[Systems/sshproof]] — authenticates outer custody and inner certificate (`E492`)
- [[Systems/custodychunks]] — reconstructs before checking critical subjects (`E493`)
