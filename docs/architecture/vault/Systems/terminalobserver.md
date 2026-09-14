---
canonical_id: "terminalobserver"
kind: system
layer: durability
currentness: changed-file
runtime_observed: false
certified: false
---
# Independent worker exit and terminal observer

[[Layers/durability]] · [[Views/Full_Architecture]]

## Purpose

Binds observer PID, waits for worker handoff, checks process exit, reconciles exact-run ephemerals and publishes terminal state.

## Historical source state

Process closure, terminal state, optional root-level receipt update and observer diagnostics.

## Limits and unknowns

No overall deadline while live worker observations succeed. Current terminal state short-circuits finalizer. Agent revision receipt location differs from finalizer root-level path. Resume handoff file is reused without generation freshness check.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3166]] — same-file-bytes
- [[Evidence/S3177]] — changed-file

## Directed relationships

- [[Systems/resources]] — reconciles worker and observer custody (`E435`)
- [[Systems/durablepublisher]] — finalizes after worker exit observation (`E440`)
- [[Systems/resourcecustody]] — verifies persisted worker exit (`E444`)
