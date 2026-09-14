---
canonical_id: "bundleera"
kind: system
layer: governance
currentness: changed-file
runtime_observed: false
certified: false
---
# MCP protocol era and connection negotiation

[[Layers/governance]] · [[Views/Full_Architecture]]

## Purpose

Classifies opening messages, probes modern discovery and pins modern or legacy server instance.

## Historical source state

Opening/probe/pinned/closed state and server channels.

## Limits and unknowns

Factory may run twice on fallback; PX discards returned serving handle and registers no application shutdown integration.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S816]] — changed-file

## Directed relationships

- [[Systems/bundlesubscriptions]] — owns modern listen routing (`E1617`)
- [[Systems/bundledispatch]] — pins instance and delivers request (`E1618`)
- [[Systems/bundleajv]] — constructs lazy default validator provider (`E1623`)
