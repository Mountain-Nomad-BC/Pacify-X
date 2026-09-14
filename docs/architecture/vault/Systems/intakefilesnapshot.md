---
canonical_id: "intakefilesnapshot"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Intake file snapshot identity

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Enumerates files and hashes path/content/size/mtime into a snapshot.

## Historical source state

File rows, counts and tree digest.

## Limits and unknowns

Not a complete filesystem identity: empty directories, links and file IDs are not recorded.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2257]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
