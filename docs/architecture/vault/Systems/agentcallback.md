---
canonical_id: "agentcallback"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Governed plan and supplied CPU or GPU callbacks

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Resolves signed Studio admission plus plan, memory and handoff hashes, creates run, reserves placement capacity, invokes supplied callback and releases capacity.

## Historical source state

Signed governed run receipt with memory/handoff hashes and placement outcome.

## Limits and unknowns

No memory items or handoff content are passed to execute_agent_plan; callback construction remains caller responsibility. This route does not invoke provider gateway and has no controller-level durable cancellation polling.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1595]] — same-file-bytes
- [[Evidence/S1582]] — same-file-bytes
- [[Evidence/S4076]] — same-file-bytes

## Directed relationships

- [[Systems/memorybroker]] — materializes supplied records during preview (`E423`)
- [[Systems/hardware]] — reserves and releases capacity around callback (`E428`)
