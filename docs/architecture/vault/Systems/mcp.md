---
canonical_id: "mcp"
kind: system
layer: host
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# MCP host adapter

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Exposes host tools through annotation-selected mutation checks and activity instrumentation.

## Historical source state

MCP actor attestations, mutation authority and activity receipts.

## Limits and unknowns

MCP observation cannot itself confer write authority.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S1150]] — same-file-bytes
- [[Evidence/S1149]] — same-file-bytes

## Directed relationships

- [[Systems/coordination]] — gates task mutations (`E004`)
- [[Systems/telemetry]] — records tool lifecycle (`E005`)
- [[Systems/mcproutes]] — wraps registered handlers with authority and activity (`E213`)
- [[Systems/graphread]] — dispatches bounded graph queries through dashboard API (`E259`)
- [[Systems/mcpobservation]] — provides succeeded invocation metadata (`E334`)
