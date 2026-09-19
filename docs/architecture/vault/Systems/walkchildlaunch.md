---
canonical_id: "walkchildlaunch"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Isolated VS Code and walker startup

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Optionally installs exact VSIX then launches ordinary/bootstrap host, native helper and walker with scoped fixtures.

## Historical source state

Host/native/walker process handles and readiness state.

## Limits and unknowns

Outer worker bounds duration; local download/walker waits depend on it; native helper uses system python rather than selected interpreter.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S614]] — changed-file

## Directed relationships

- [[Systems/walknetworkenv]] — passes filtered proxy environment (`E1532`)
- [[Systems/walkstorageobserve]] — waits CDP and isolated storage (`E1533`)
- [[Systems/operationalbootstrap]] — loads bootstrap only in bootstrap mode (`E1534`)
- [[Systems/operationalwalkprobes]] — spawns live UI walker (`E1535`)
- [[Systems/walkchildfinalize]] — finalizes child handles in finally (`E1536`)
- [[Systems/iwadmission]] — supplies owned-host environment and token (`E1562`)
