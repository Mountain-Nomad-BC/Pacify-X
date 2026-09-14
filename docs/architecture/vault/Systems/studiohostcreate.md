---
canonical_id: "studiohostcreate"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Host immutable draft creation coordinator

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Revalidates allocation or absence, confirms create, consumes proof and dispatches backend save.

## Historical source state

Correlated cancel/conflict/create outcomes.

## Limits and unknowns

Host coordination is not backend atomic publication; confirmation can separate observation from execution.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1289]] — same-file-bytes
- [[Evidence/S1009]] — changed-file

## Directed relationships

- [[Systems/studiotrustregistry]] — asserts and consumes allocation token (`E1024`)
- [[Systems/versionallocation]] — refreshes allocation binding before confirmation (`E1025`)
- [[Systems/studioexternalreauth]] — reauthenticates external lineage after confirmation (`E1026`)
- [[Systems/studiomaterializedtree]] — materializes skill editor input before source admission (`E1028`)
- [[Systems/studioapprovaldispatch]] — admits skill source then approves backend create (`E1031`)
- [[Systems/studiohostreceipt]] — classifies returned commit evidence (`E1032`)
