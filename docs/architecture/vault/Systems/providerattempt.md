---
canonical_id: "providerattempt"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Provider attempt and terminal publication

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Reserves one invocation, publishes start, calls adapter, settles usage, publishes terminal event and returns receipt.

## Historical source state

Budget reservation/settlement and separate event revisions.

## Limits and unknowns

Budget and event commits are separate. Completed-event failure can leave settled success while the caller receives an error. No global transaction wraps external provider execution.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2722]] — same-file-bytes

## Directed relationships

- [[Systems/budget]] — reserves before start and settles before terminal event (`E399`)
- [[Systems/telemetry]] — publishes start and terminal in separate steps (`E400`)
- [[Systems/provideradapters]] — invokes caller-supplied adapter (`E401`)
- [[Systems/providerfallback]] — allows one fallback after typed invocation failure (`E402`)
