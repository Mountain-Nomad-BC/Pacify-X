---
canonical_id: "memorycontext"
kind: system
layer: memory
currentness: changed-file
runtime_observed: false
certified: false
---
# Layer quotas and reversible tool offload

[[Layers/memory]] · [[Views/Full_Architecture]]

## Purpose

Assembles ranked summaries and evidence pointers with layer quotas; separately compacts older large tool results into hash-addressed objects/pointers when apply is true.

## Historical source state

ContextPackage, dropped IDs, compacted messages and optional OffloadPointer artifacts.

## Limits and unknowns

Assembly uses characters and omits join separators from reported usage. Compaction is best effort; preview pointers may have no persisted object. Restore verifies content hash without checking locator containment or pointer project.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2364]] — changed-file

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
