---
canonical_id: "envworker"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Discovery promise and worker ownership

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Coalesces ordinary discovery, passes fresh generations into governor supersession and wraps filesystem worker with45s timeout/abort.

## Historical source state

Promise ownership, abort/deadline result and worker envelope.

## Limits and unknowns

Latest coordinator alone does not cancel old work. Worker termination promise is not awaited before settlement. Probe termination and direct-child exit do not independently prove all descendant closure.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1148]] — same-file-bytes
- [[Evidence/S969]] — same-file-bytes
- [[Evidence/S985]] — same-file-bytes
- [[Evidence/S1101]] — changed-file
- [[Evidence/S1167]] — same-file-bytes

## Directed relationships

- [[Systems/envcollect]] — runs filesystem interpretation in a worker after tool probes (`E371`)
- [[Systems/hostgovernor]] — uses shared discovery supersession and CPU worker pool (`E383`)
