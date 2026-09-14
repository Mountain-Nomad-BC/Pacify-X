---
canonical_id: "streams"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Project stream orchestrator

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Uses registered project/workspace workflows, preflight checks, effects and executable handler bindings to run bounded operations.

## Historical source state

ProjectStreamContext, execution checkpoints and named outputs.

## Limits and unknowns

Completion checks output presence and deadline/lease boundaries; that alone is not independent semantic verification.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2688]] — same-file-bytes

## Directed relationships

- [[Systems/improvement]] — runs continuous-improvement handler (`E084`)
