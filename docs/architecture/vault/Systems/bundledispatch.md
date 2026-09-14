---
canonical_id: "bundledispatch"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# SDK request context cancellation and dispatch

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Checks envelope/method, creates abort controller and dispatches handler asynchronously.

## Historical source state

Per-request context, signal, reply and in-flight map.

## Limits and unknowns

Cancellation is cooperative; zero ID is skipped, duplicate IDs replace controller entries and handlers are not globally concurrency bounded.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S796]] — changed-file

## Directed relationships

- [[Systems/bundletools]] — passes request context and parsed arguments (`E1619`)
