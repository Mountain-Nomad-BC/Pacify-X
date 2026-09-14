---
canonical_id: "detachedworker"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Durable Studio worker and terminal observer

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Launches Studio work beyond a one-shot CLI lifetime and reconciles terminal state only after the identified worker exits.

## Historical source state

Signed worker binding, resource/PID identity, finalizing checkpoint and terminal state.

## Limits and unknowns

Paused exit is recoverable; unexpected worker exit fails or cancels. A terminal target is not yet evidence that the worker is gone. The terminal observer retries recognized finalization errors for up to 30 seconds, records non-authoritative diagnostics, and reconciles its own process in finally.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3186]] — changed-file
- [[Evidence/S3185]] — changed-file
- [[Evidence/S3171]] — same-file-bytes
- [[Evidence/S3159]] — same-file-bytes

## Directed relationships

- [[Systems/resources]] — binds and reconciles exact worker identity (`E186`)
- [[Systems/supervisor]] — finalizes durable state after worker exit (`E187`)
