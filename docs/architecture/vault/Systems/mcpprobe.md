---
canonical_id: "mcpprobe"
kind: system
layer: evidence
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# MCP context invocation probe

[[Layers/evidence]] · [[Views/Full_Architecture]]

## Purpose

Starts the bundled stdio server, initializes it, calls the context snapshot and retains a process receipt.

## Historical source state

Initialization metadata, truthy structured-content condition and child-exit receipt.

## Limits and unknowns

An empty object passes the result predicate. Responses have bounded polling, but final child-close wait has no timeout. Child spawn precedes initial receipt; no probe was executed here.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S530]] — same-file-bytes

## Directed relationships

- [[Systems/mcpbundle]] — starts bundle and requests context snapshot (`E335`)
