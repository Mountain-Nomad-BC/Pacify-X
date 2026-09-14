---
canonical_id: "teaminventoryworker"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Team inventory worker and synchronous route

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Offloads inventory to a worker for the dashboard with timeout/abort handling; MCP invokes the same inventory synchronously.

## Historical source state

Worker result/error or direct preview; owner cancellation and deadline state.

## Limits and unknowns

Worker terminate promises are not awaited before settling the wrapper. The synchronous MCP path has no worker deadline, even though the same inventory has per-file and accepted-file bounds.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1330]] — same-file-bytes
- [[Evidence/S1331]] — same-file-bytes
- [[Evidence/S1127]] — changed-file
- [[Evidence/S856]] — same-file-bytes

## Directed relationships

- [[Systems/teampack]] — calls shared package inventory in worker (`E369`)
