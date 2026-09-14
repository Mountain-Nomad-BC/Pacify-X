---
canonical_id: "supervisor"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Process supervision and run control

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Owns child-process limits, cancellation, timeouts, capture and durable pause/resume/stop state.

## Historical source state

Process tree records, output capture, durable run checkpoints and terminal status.

## Limits and unknowns

A process exit is only one input to success; lifecycle cleanup and outcome evidence still matter.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2620]] — changed-file
- [[Evidence/S3154]] — same-file-bytes
- [[Evidence/S1168]] — same-file-bytes

## Directed relationships

- [[Systems/resources]] — registers and reconciles owned resources (`E047`)
