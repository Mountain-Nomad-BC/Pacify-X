---
canonical_id: "evidenceindexwriter"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Current evidence index CLI publication

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Chooses build-only or two-target publication before returning index validity.

## Historical source state

Index JSON and exit status.

## Limits and unknowns

Invalid index may already be published; two replacements not atomic as pair.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3451]] — same-file-bytes
- [[Evidence/S2090]] — changed-file

## Directed relationships

- [[Systems/currentindex]] — builds or publishes core current index (`E1196`)
