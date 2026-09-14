---
canonical_id: "extensionapprovalroutes"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# Host approval and owned-harness route selection

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Routes ordinary host prompts and explicit owned-harness environment flags through different action paths.

## Historical source state

Approval decision and signed backend capabilities for Studio operations.

## Limits and unknowns

Harness flags bypass selected prompts; environment move/restore receives approved=true from typed webview route without an additional host prompt.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1094]] — changed-file
- [[Evidence/S996]] — changed-file
- [[Evidence/S1019]] — changed-file

## Directed relationships

- [[Systems/hostcompletionroute]] — authorizes Studio model preparation (`E1495`)
- [[Systems/extensionmemoryconnect]] — selects prompt or owned fixture path (`E1496`)
- [[Systems/extensionlifecyclepublication]] — passes exact target and manager approval (`E1497`)
