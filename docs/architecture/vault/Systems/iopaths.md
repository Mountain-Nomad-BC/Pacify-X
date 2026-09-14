---
canonical_id: "iopaths"
kind: system
layer: discovery
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Typed capability path ranking

[[Layers/discovery]] · [[Views/Full_Architecture]]

## Purpose

Finds bounded compatible input/output paths and ranks the considered paths using risk, mutation count, declared cost, latency and evidence status.

## Historical source state

Ranked capability-ID tuples and score explanations.

## Limits and unknowns

Evidence current is supplied metadata; the function does not hydrate or run the listed capabilities, and ranking is over a bounded candidate set. A production caller was not established in the searched surfaces; this node is deliberately shown without a behavioral edge.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S2224]] — same-file-bytes
- [[Evidence/S2225]] — same-file-bytes

## Directed relationships

No outgoing semantic relationship recorded. This is not proof there is no consumer.
