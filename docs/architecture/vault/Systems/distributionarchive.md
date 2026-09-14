---
canonical_id: "distributionarchive"
kind: system
layer: discovery
currentness: changed-file
runtime_observed: false
certified: false
---
# Wheel and sdist member inspection

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Reads members, computes hashes and extracts Version from package metadata.

## Historical source state

Member records and last matching metadata version.

## Limits and unknowns

No full wheel/RECORD semantics or aggregate decompression cap.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2884]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
