---
canonical_id: "skilleditfiles"
kind: system
layer: acquisition
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Skill editor native file synthesis and identity synchronization

[[Layers/acquisition]] · [[Views/Full_Architecture]]

## Purpose

Creates native package files and synchronizes manifest/identity before host creation.

## Historical source state

Text file map with candidate validation.

## Limits and unknowns

Editor path checks are weaker than host materializer; synchronization overwrites skill.yaml from capability manifest.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S333]] — same-file-bytes

## Directed relationships

- [[Systems/studioeditorinput]] — offers text file map to stricter host materializer (`E1042`)
