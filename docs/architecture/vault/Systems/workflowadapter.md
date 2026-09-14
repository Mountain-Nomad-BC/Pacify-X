---
canonical_id: "workflowadapter"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Closed workflow adapter and validation worker

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Verifies signed task and current authority hashes, executes identity/increment/double/fail/sleep and evaluates declarative checks.

## Historical source state

Liveness and completed JSON lines with output and validation details.

## Limits and unknowns

Adapter runs before node-kind/config/approval marker checks. No arbitrary capability dispatcher; worker trusts signed host-consumed marker and does not consume task nonce.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3305]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
