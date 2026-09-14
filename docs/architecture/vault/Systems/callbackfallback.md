---
canonical_id: "callbackfallback"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Callback execution retry and CPU fallback

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Calls selected device callback, retries selected RuntimeError messages with smaller batches then invokes CPU callback.

## Historical source state

Result and branch-derived device telemetry, optional measured benchmark.

## Limits and unknowns

No measured callback hardware, rollback or output-equivalence check during fallback. CPU fallback unconditional after retries; policy fallback flag is not accepted by this function.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2233]] — same-file-bytes
- [[Evidence/S2232]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
