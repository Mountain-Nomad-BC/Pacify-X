---
canonical_id: "learningevidence"
kind: system
layer: memory
currentness: changed-file
runtime_observed: false
certified: false
---
# Learning evidence references and source snapshots

[[Layers/memory]] · [[Views/Full_Architecture]]

## Purpose

Snapshots declared active local sources and accepts hash-only or path-plus-hash evidence.

## Historical source state

Source inventory identities and evidence reference records.

## Limits and unknowns

Hash-only references do not resolve bytes; hashed file contents are not interpreted as trial results.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2283]] — changed-file
- [[Evidence/S2275]] — changed-file

## Directed relationships

- [[Systems/learningtrials]] — supplies references for submitted winners and research (`E658`)
- [[Systems/knowledgepublication]] — is resnapshotted before canonical commit (`E662`)
