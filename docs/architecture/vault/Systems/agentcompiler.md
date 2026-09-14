---
canonical_id: "agentcompiler"
kind: system
layer: execution
currentness: changed-file
runtime_observed: false
certified: false
---
# Agent graph and specification compiler

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Binds the editor graph, layout and compiled AgentSpec with deterministic hashes and verifies that all representations agree.

## Historical source state

Graph envelope, layout envelope, compiler receipt and exact AgentSpec identity.

## Limits and unknowns

Visual layout does not grant execution authority; mismatch blocks runtime use.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1520]] — changed-file
- [[Evidence/S1526]] — changed-file
- [[Evidence/S1583]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
