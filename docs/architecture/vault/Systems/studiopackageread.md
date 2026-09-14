---
canonical_id: "studiopackageread"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Scoped Studio package editor reader

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Reads bounded exact UTF-8 packages under canonical/preserved or physical project Studio roots.

## Historical source state

Editor files, source scope, tree digest and native completeness.

## Limits and unknowns

Preserved originals can be incomplete packages; path checks do not constitute a locked coherent tree snapshot.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1319]] — same-file-bytes

## Directed relationships

- [[Systems/studioeditorinput]] — normalizes exact decoded tree and computes digest (`E1030`)
