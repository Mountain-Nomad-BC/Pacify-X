---
canonical_id: "agent"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Agent Studio runtime

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Creates/tests/admit agent revisions, materializes governed context, runs owned harnesses or completes host-executed sessions.

## Historical source state

Agent revisions, immutable plans, admission receipts, session state and execution receipts.

## Limits and unknowns

Host-executed and PX-owned harness routes have different execution ownership; both require their declared contracts.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1603]] — same-file-bytes
- [[Evidence/S1602]] — same-file-bytes
- [[Evidence/S1600]] — same-file-bytes

## Directed relationships

- [[Systems/supervisor]] — launches owned harness execution (`E045`)
- [[Systems/hostmodel]] — authorizes and completes host model run (`E113`)
- [[Systems/agentcompiler]] — verifies graph and spec identity (`E183`)
- [[Systems/detachedworker]] — launches owned durable agent worker (`E184`)
- [[Systems/localworker]] — runs authenticated deterministic task envelope (`E200`)
- [[Systems/agentpreflight]] — tests structural identity then admits authority closure (`E419`)
- [[Systems/studiophys]] — uses bounded revision filesystem primitives (`E464`)
- [[Systems/capacityleases]] — reserves before callback and releases after outcome (`E505`)
- [[Systems/callbackfallback]] — executes caller CPU or GPU functions (`E516`)
- [[Systems/agenttypedgraph]] — projects draft AgentSpec (`E943`)
