---
canonical_id: "hostgovernor"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Host work queues and circuit recovery

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Coalesces keyed producers, applies per-pool priority/concurrency/queue policies, supersedes older keys and races active work against abort/deadline.

## Historical source state

Promise slots, queue depth, cancellation reasons, circuits and bounded recent latency metrics.

## Limits and unknowns

Actual cleanup belongs to producers. Cancelled half-open circuit trials do not clear the halfOpenActive flag. Same-key join happens before considering new options.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1353]] — changed-file
- [[Evidence/S1483]] — same-file-bytes

## Directed relationships

- [[Systems/hostcapture]] — supplies abort signal to governed subprocess producer (`E377`)
