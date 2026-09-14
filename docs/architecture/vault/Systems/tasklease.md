---
canonical_id: "tasklease"
kind: system
layer: scope
currentness: changed-file
runtime_observed: false
certified: false
---
# Coordination claims and progress leases

[[Layers/scope]] · [[Views/Full_Architecture]]

## Purpose

Claims dependency-ready work with bounded ownership, overlap checks and per-target fencing generations; accepts owner progress and cumulative reported usage.

## Historical source state

Actor/session-bound lease, expiry, fencing tokens, progress receipts and usage status.

## Limits and unknowns

Fencing checks run for supplied token entries. Reported budget excess marks a task blocked; this function does not itself terminate a worker.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S948]] — changed-file

## Directed relationships

- [[Systems/taskreconcile]] — requires completed owner work and live claim (`E218`)
- [[Systems/coordpublish]] — commits lease and progress transitions (`E232`)
