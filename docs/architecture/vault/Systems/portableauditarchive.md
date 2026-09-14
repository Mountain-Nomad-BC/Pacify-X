---
canonical_id: "portableauditarchive"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Portable audit archive and checksum publication

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Packages payload hashes, exclusions, prerequisite JSON and optional attestation.

## Historical source state

ZIP plus separate external SHA-256 file.

## Limits and unknowns

Pair publication is not atomic; metadata inclusion is not certification.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2607]] — changed-file

## Directed relationships

- [[Systems/portableauditverify]] — publishes archive and checksum for independent verification (`E1100`)
