---
canonical_id: "agentworkerpublication"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Deterministic worker task and cleanup publication

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Registers task workspace, signs task, runs supervised deterministic harness, interprets final stdout JSON, reclaims task content, then publishes terminal/finalizing state and receipt.

## Historical source state

Owned task/process resources, cleanup/process receipts and durable session state.

## Limits and unknowns

Running state is published before resource/signing setup outside try. Cleanup failure can prevent terminal publication; JSON parse does not assert mapping shape before .get. Asynchronous terminal closure delegates to Studio worker owner.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1571]] — same-file-bytes

## Directed relationships

- [[Systems/supervisor]] — runs bounded signed-task worker and requires tree closure (`E427`)
- [[Systems/studiolaunch]] — starts detached session for asynchronous execution (`E429`)
- [[Systems/localagenttools]] — supervises closed deterministic task subprocess (`E433`)
- [[Systems/durablepublisher]] — publishes worker state and checkpoint (`E439`)
